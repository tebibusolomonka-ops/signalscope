import hashlib
import io
import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from signalscope.domain.organizations.backup_policy import (
    OrganizationBackupFrequency,
    OrganizationBackupPolicy,
)
from signalscope.domain.organizations.backup_service import OrganizationBackupService
from signalscope.domain.organizations.export_archive import OrganizationExportArchive
from signalscope.domain.organizations.export_record import (
    OrganizationExport,
    OrganizationExportStatus,
)

ORGANIZATION_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


class MemoryBlobs:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.values[key] = data

    async def get(self, key: str) -> bytes:
        return self.values[key]

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.values


class ScalarResult:
    def __init__(self, values: list[OrganizationExport]) -> None:
        self.values = values

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.values)


class FakeSession:
    def __init__(
        self, policy: OrganizationBackupPolicy, old_exports: list[OrganizationExport] | None = None
    ) -> None:
        self.policy = policy
        self.old_exports = old_exports or []
        self.added: list[Any] = []
        self.commits = 0

    async def get(self, model: Any, key: Any) -> Any:
        if model is OrganizationBackupPolicy:
            assert key == ORGANIZATION_ID
            return self.policy
        if model is OrganizationExport:
            return next(
                (value for value in self.added if isinstance(value, model) and value.id == key),
                None,
            )
        raise AssertionError(f"Unexpected model: {model}")

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if isinstance(value, OrganizationExport) and value.id is None:
                value.id = uuid.UUID("33333333-3333-3333-3333-333333333333")

    async def scalars(self, statement: Any) -> ScalarResult:
        return ScalarResult(self.old_exports)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


class FakeArchive:
    def __init__(self, data: bytes, valid: bool = True) -> None:
        self.data = data
        self.valid = valid
        self.include_assets: bool | None = None

    async def build(
        self, organization_id: uuid.UUID, *, include_assets: bool = True
    ) -> OrganizationExportArchive:
        assert organization_id == ORGANIZATION_ID
        self.include_assets = include_assets
        data = self.data if self.valid else b"not a zip"
        return OrganizationExportArchive(
            data=data, sha256="a" * 64, size_bytes=len(data), manifest={}
        )


def policy(**values: Any) -> OrganizationBackupPolicy:
    fields = {
        "organization_id": ORGANIZATION_ID,
        "enabled": True,
        "frequency": OrganizationBackupFrequency.DAILY,
        "retention_count": 2,
        "include_assets": False,
    }
    return OrganizationBackupPolicy(**(fields | values))


def valid_archive() -> bytes:
    organization = (json.dumps({"id": str(ORGANIZATION_ID)}) + "\n").encode()
    manifest = {
        "format_version": "2",
        "organization_id": str(ORGANIZATION_ID),
        "created_at": NOW.isoformat(),
        "record_counts": {"organization": 1},
        "assets": [],
        "files": [
            {
                "path": "organization.json",
                "size_bytes": len(organization),
                "sha256": hashlib.sha256(organization).hexdigest(),
            }
        ],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("organization.json", organization)
    return output.getvalue()


@pytest.mark.anyio
async def test_success_updates_policy_and_stores_verified_export() -> None:
    session = FakeSession(policy())
    blobs = MemoryBlobs()
    service = OrganizationBackupService(session, blobs, clock=lambda: NOW)  # type: ignore[arg-type]
    fake_archive = FakeArchive(valid_archive())
    service.archive = fake_archive  # type: ignore[assignment]

    export = await service.run(ORGANIZATION_ID, USER_ID)

    assert export.status is OrganizationExportStatus.COMPLETED
    assert export.sha256 == "a" * 64
    assert export.artifact_key in blobs.values
    assert session.policy.last_run_at == NOW
    assert session.policy.next_run_at == NOW + timedelta(days=1)
    assert fake_archive.include_assets is False
    assert session.commits == 2


@pytest.mark.anyio
async def test_verification_failure_does_not_update_policy() -> None:
    session = FakeSession(policy())
    blobs = MemoryBlobs()
    service = OrganizationBackupService(session, blobs, clock=lambda: NOW)  # type: ignore[arg-type]
    service.archive = FakeArchive(b"not a zip", valid=False)  # type: ignore[assignment]

    export = await service.run(ORGANIZATION_ID, USER_ID)

    assert export.status is OrganizationExportStatus.FAILED
    assert export.artifact_key is not None
    assert export.artifact_key.startswith("organization-backups/")
    assert export.safe_error == "Backup export verification failed."
    assert session.policy.last_run_at is None
    assert session.policy.next_run_at == NOW + timedelta(days=1)
    assert blobs.values == {}
    assert session.commits == 2


@pytest.mark.anyio
async def test_weekly_backup_includes_assets_and_expires_only_old_backups() -> None:
    old_backup = OrganizationExport(
        id=uuid.uuid4(),
        organization_id=ORGANIZATION_ID,
        requested_by_user_id=USER_ID,
        status=OrganizationExportStatus.COMPLETED,
        format_version="2",
        artifact_key="organization-backups/old.zip",
        size_bytes=20,
        sha256="b" * 64,
        finished_at=NOW - timedelta(days=7),
    )
    manual = OrganizationExport(
        id=uuid.uuid4(),
        organization_id=ORGANIZATION_ID,
        requested_by_user_id=USER_ID,
        status=OrganizationExportStatus.COMPLETED,
        format_version="2",
        artifact_key="organization-exports/manual.zip",
        size_bytes=20,
        sha256="c" * 64,
        finished_at=NOW - timedelta(days=8),
    )
    session = FakeSession(
        policy(
            frequency=OrganizationBackupFrequency.WEEKLY,
            retention_count=1,
            include_assets=True,
        ),
        [old_backup],
    )
    blobs = MemoryBlobs()
    blobs.values["organization-backups/old.zip"] = b"old"
    blobs.values["organization-exports/manual.zip"] = b"manual"
    service = OrganizationBackupService(session, blobs, clock=lambda: NOW)  # type: ignore[arg-type]
    fake_archive = FakeArchive(valid_archive())
    service.archive = fake_archive  # type: ignore[assignment]

    await service.run(ORGANIZATION_ID, USER_ID)

    assert session.policy.next_run_at == NOW + timedelta(days=7)
    assert fake_archive.include_assets is True
    assert old_backup.status is OrganizationExportStatus.EXPIRED
    assert "organization-backups/old.zip" not in blobs.values
    assert manual.status is OrganizationExportStatus.COMPLETED
    assert blobs.values["organization-exports/manual.zip"] == b"manual"
