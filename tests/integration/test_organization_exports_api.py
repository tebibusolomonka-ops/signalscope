import dataclasses
import io
import zipfile
from collections.abc import AsyncIterator
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
from signalscope.domain.organizations.export_record import OrganizationExportStatus
from tenancy_helpers import Tenants, add_document, add_source, make_tenants

pytestmark = pytest.mark.anyio


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
    assert listed.status_code == detail.status_code == downloaded.status_code == 200
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


async def test_system_admin_can_manage_exports(
    export_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await tenant_data(export_client, session_factory)
    response = await export_client.post(
        f"/organizations/{tenants.a.id}/exports", headers=tenants.system
    )
    assert response.status_code == 201
