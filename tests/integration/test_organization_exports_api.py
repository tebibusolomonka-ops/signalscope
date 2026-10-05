import dataclasses
import io
import uuid
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from password_helpers import fast_hasher
from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.core.settings import Settings
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.organizations.export_cleanup import OrganizationExportCleanupService
from signalscope.domain.organizations.export_record import (
    OrganizationExport,
    OrganizationExportStatus,
)
from tenancy_helpers import Tenants, add_document, add_source, make_tenants

pytestmark = pytest.mark.anyio


class CleanupBlobs:
    def __init__(self, keys: set[str]) -> None:
        self.keys = keys
        self.deleted: list[str] = []

    async def delete(self, key: str) -> None:
        self.keys.discard(key)
        self.deleted.append(key)

    async def put(self, key: str, data: bytes) -> None:
        self.keys.add(key)

    async def get(self, key: str) -> bytes:
        return b""

    async def exists(self, key: str) -> bool:
        return key in self.keys


@pytest.fixture
async def export_client(
    database_engine: AsyncEngine,
    migrated_database: Settings,
    tmp_path: Path,
) -> AsyncIterator[httpx.AsyncClient]:
    settings = dataclasses.replace(
        migrated_database, auth_enabled=True, blob_dir=tmp_path / "blobs"
    )
    app = create_app(settings)
    app.state.password_hasher = fast_hasher()
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def tenant_data(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> Tenants:
    tenants = await make_tenants(client, session_factory)
    source_id = await add_source(session_factory, tenants.a.id)
    await add_document(session_factory, source_id, "Tenant article", ["Tenant evidence."])
    other_source_id = await add_source(session_factory, tenants.b.id, "Other feed")
    await add_document(session_factory, other_source_id, "Other article", ["Other evidence."])
    return tenants


async def test_create_list_detail_download_and_audit(
    export_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await tenant_data(export_client, session_factory)
    path = f"/organizations/{tenants.a.id}/exports"

    created = await export_client.post(path, headers=tenants.a.headers["owner"])

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == OrganizationExportStatus.COMPLETED
    assert "artifact_key" not in body
    export_id = body["id"]
    listed = await export_client.get(path, headers=tenants.a.headers["admin"])
    detail = await export_client.get(f"{path}/{export_id}", headers=tenants.a.headers["admin"])
    downloaded = await export_client.get(
        f"{path}/{export_id}/download", headers=tenants.a.headers["owner"]
    )
    verified = await export_client.post(
        f"{path}/{export_id}/verify", headers=tenants.a.headers["admin"]
    )
    assert listed.status_code == detail.status_code == downloaded.status_code == 200
    assert verified.status_code == 200
    assert verified.json()["valid"] is True
    assert verified.json()["checked_files"] > 0
    assert [item["id"] for item in listed.json()] == [export_id]
    assert detail.json() == body
    assert downloaded.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        documents = archive.read("documents.jsonl").decode("utf-8")
    assert "Tenant article" in documents
    assert "Other article" not in documents

    async with session_factory() as session:
        events = list(
            await session.scalars(
                select(SecurityAuditEvent).where(
                    SecurityAuditEvent.action == "organization.export_created"
                )
            )
        )
    assert len(events) == 1 and str(events[0].resource_id) == export_id


@pytest.mark.parametrize("role", ["member", "viewer"])
async def test_members_cannot_manage_exports(
    export_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    role: str,
) -> None:
    tenants = await tenant_data(export_client, session_factory)
    response = await export_client.get(
        f"/organizations/{tenants.a.id}/exports", headers=tenants.a.headers[role]
    )
    assert response.status_code == 403

    owner_created = await export_client.post(
        f"/organizations/{tenants.a.id}/exports", headers=tenants.a.headers["owner"]
    )
    verify = await export_client.post(
        f"/organizations/{tenants.a.id}/exports/{owner_created.json()['id']}/verify",
        headers=tenants.a.headers[role],
    )
    assert verify.status_code == 403


async def test_wrong_organization_does_not_reveal_export(
    export_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await tenant_data(export_client, session_factory)
    created = await export_client.post(
        f"/organizations/{tenants.a.id}/exports", headers=tenants.a.headers["owner"]
    )
    export_id = created.json()["id"]

    response = await export_client.get(
        f"/organizations/{tenants.b.id}/exports/{export_id}",
        headers=tenants.b.headers["owner"],
    )
    assert response.status_code == 404

    unknown = await export_client.post(
        f"/organizations/{tenants.a.id}/exports/{uuid.uuid4()}/verify",
        headers=tenants.a.headers["owner"],
    )
    assert unknown.status_code == 404


async def test_verify_reports_corrupt_archive(
    export_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    tenants = await tenant_data(export_client, session_factory)
    created = await export_client.post(
        f"/organizations/{tenants.a.id}/exports", headers=tenants.a.headers["owner"]
    )
    export_id = created.json()["id"]
    async with session_factory() as session:
        stored = await session.get(OrganizationExport, export_id)
        assert stored is not None and stored.artifact_key is not None
        artifact_key = stored.artifact_key
    (tmp_path / "blobs").joinpath(*artifact_key.split("/")).write_bytes(b"not a zip")

    response = await export_client.post(
        f"/organizations/{tenants.a.id}/exports/{export_id}/verify",
        headers=tenants.a.headers["owner"],
    )

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert response.json()["problems"] == ["Archive is not a readable ZIP file."]


async def test_system_admin_can_manage_exports(
    export_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await tenant_data(export_client, session_factory)
    response = await export_client.post(
        f"/organizations/{tenants.a.id}/exports", headers=tenants.system
    )
    assert response.status_code == 201


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": -1},
        {"limit": 101},
        {"offset": -1},
    ],
)
async def test_export_list_rejects_unsafe_pagination(
    export_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    params: dict[str, int],
) -> None:
    tenants = await make_tenants(export_client, session_factory)

    response = await export_client.get(
        f"/organizations/{tenants.a.id}/exports",
        headers=tenants.a.headers["owner"],
        params=params,
    )

    assert response.status_code == 422


async def test_export_list_accepts_maximum_limit_and_applies_offset(
    export_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(export_client, session_factory)
    records = [
        OrganizationExport(
            organization_id=tenants.a.id,
            requested_by_user_id=tenants.a.owner_id,
            status=OrganizationExportStatus.COMPLETED,
            format_version="2",
        )
        for _ in range(2)
    ]
    async with session_factory() as session:
        session.add_all(records)
        await session.commit()

    response = await export_client.get(
        f"/organizations/{tenants.a.id}/exports",
        headers=tenants.a.headers["owner"],
        params={"limit": 100, "offset": 1},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_export_cleanup_keeps_recent_and_active_exports_and_obeys_limit(
    export_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(export_client, session_factory)
    now = datetime(2026, 10, 3, tzinfo=UTC)
    old = now - timedelta(days=31)
    recent = now - timedelta(days=1)
    exports = [
        OrganizationExport(
            organization_id=tenants.a.id,
            requested_by_user_id=tenants.a.owner_id,
            status=status,
            format_version="2",
            created_at=created_at,
            finished_at=created_at,
            expires_at=expires_at,
            artifact_key=f"organization-exports/{name}.zip",
        )
        for name, status, created_at, expires_at in (
            ("old-one", OrganizationExportStatus.COMPLETED, old, None),
            ("old-two", OrganizationExportStatus.FAILED, old, None),
            ("explicit", OrganizationExportStatus.COMPLETED, recent, now - timedelta(seconds=1)),
            ("recent", OrganizationExportStatus.COMPLETED, recent, None),
            ("active", OrganizationExportStatus.RUNNING, old, now - timedelta(days=1)),
        )
    ]
    keys = {item.artifact_key for item in exports if item.artifact_key is not None}
    blobs = CleanupBlobs(keys)
    async with session_factory() as session:
        session.add_all(exports)
        await session.commit()
        service = OrganizationExportCleanupService(session, blobs, lambda: now)
        preview = await service.preview(30, 1)
        result = await service.run(30, 2)
    assert (preview.eligible, preview.expired) == (1, 0)
    assert (result.eligible, result.expired) == (2, 2)
    async with session_factory() as session:
        stored = list(
            await session.scalars(
                select(OrganizationExport).where(
                    OrganizationExport.id.in_([item.id for item in exports])
                )
            )
        )
    statuses = {str(item.id): item.status for item in stored}
    assert statuses[str(exports[3].id)] is OrganizationExportStatus.COMPLETED
    assert statuses[str(exports[4].id)] is OrganizationExportStatus.RUNNING
    assert sum(status is OrganizationExportStatus.EXPIRED for status in statuses.values()) == 2
    assert len(blobs.deleted) == 2
