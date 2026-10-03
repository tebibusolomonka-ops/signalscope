import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from signalscope.domain.organizations.export_cleanup import OrganizationExportCleanupService
from signalscope.domain.organizations.export_record import (
    OrganizationExport,
    OrganizationExportStatus,
)

NOW = datetime(2026, 10, 3, tzinfo=UTC)


class MemoryBlobs:
    def __init__(self, values: set[str] | None = None) -> None:
        self.values = values or set()
        self.deleted: list[str] = []

    async def delete(self, key: str) -> None:
        self.values.discard(key)
        self.deleted.append(key)

    async def put(self, key: str, data: bytes) -> None:
        self.values.add(key)

    async def get(self, key: str) -> bytes:
        return b"" if key in self.values else b""

    async def exists(self, key: str) -> bool:
        return key in self.values


def export(*, artifact_key: str | None = "exports/old.zip") -> OrganizationExport:
    return OrganizationExport(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        requested_by_user_id=uuid.uuid4(),
        status=OrganizationExportStatus.COMPLETED,
        format_version="2",
        artifact_key=artifact_key,
        size_bytes=10,
        sha256="a" * 64,
    )


def session_with(exports: list[OrganizationExport]) -> Mock:
    session = Mock()
    session.scalars = AsyncMock(return_value=exports)
    session.commit = AsyncMock()
    return session


@pytest.mark.anyio
async def test_preview_does_not_change_or_delete_exports() -> None:
    item = export()
    session = session_with([item])
    blobs = MemoryBlobs({"exports/old.zip"})

    result = await OrganizationExportCleanupService(session, blobs, lambda: NOW).preview(30, 10)

    assert (result.eligible, result.expired) == (1, 0)
    assert item.status is OrganizationExportStatus.COMPLETED
    assert blobs.deleted == []
    session.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_apply_expires_export_after_deleting_artifact() -> None:
    item = export()
    session = session_with([item])
    blobs = MemoryBlobs({"exports/old.zip"})

    result = await OrganizationExportCleanupService(session, blobs, lambda: NOW).run(30, 10)

    assert (result.eligible, result.expired) == (1, 1)
    assert blobs.deleted == ["exports/old.zip"]
    assert item.status is OrganizationExportStatus.EXPIRED
    assert (item.artifact_key, item.size_bytes, item.sha256) == (None, None, None)
    session.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_apply_handles_missing_artifact_key() -> None:
    item = export(artifact_key=None)
    session = session_with([item])
    blobs = MemoryBlobs()

    result = await OrganizationExportCleanupService(session, blobs, lambda: NOW).run(30, 1)

    assert result.expired == 1
    assert blobs.deleted == []
