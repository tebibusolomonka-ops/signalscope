import dataclasses
import uuid
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
from signalscope.domain.organizations.export_archive import OrganizationExportArchiveService
from signalscope.domain.organizations.export_inventory import OrganizationExportInventoryService
from signalscope.domain.organizations.restore_record import OrganizationRestore
from signalscope.domain.sources.model import Source
from tenancy_helpers import add_document, add_source, make_tenants

pytestmark = pytest.mark.anyio

ZIP = {"content-type": "application/zip"}


@pytest.fixture
async def restore_client(
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


async def make_archive(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID
) -> bytes:
    source_id = await add_source(session_factory, organization_id, "Archived feed")
    await add_document(session_factory, source_id, "Archived report", ["Harbour rose."])
    async with session_factory() as session:
        archive = await OrganizationExportArchiveService(
            OrganizationExportInventoryService(session), None
        ).build(organization_id, include_assets=False)
    return archive.data


async def restore_run_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[SecurityAuditEvent]:
    async with session_factory() as session:
        return list(
            await session.scalars(
                select(SecurityAuditEvent).where(
                    SecurityAuditEvent.action == "organization.restore_run"
                )
            )
        )


async def test_system_admin_applies_restore_and_records_audit(
    restore_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(restore_client, session_factory)
    data = await make_archive(session_factory, tenants.a.id)

    response = await restore_client.post(
        f"/organizations/{tenants.b.id}/restore?confirm=true",
        content=data,
        headers={**tenants.system, **ZIP},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["target_organization_id"] == str(tenants.b.id)

    async with session_factory() as session:
        restored = await session.scalar(
            select(Source).where(Source.organization_id == tenants.b.id)
        )
    assert restored is not None and restored.name == "Archived feed"

    events = await restore_run_events(session_factory)
    assert len(events) == 1
    assert events[0].details == {"reason": "completed"}
    assert events[0].resource_id == uuid.UUID(body["id"])


async def test_restore_denied_for_non_system_admin(
    restore_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(restore_client, session_factory)
    data = await make_archive(session_factory, tenants.a.id)

    response = await restore_client.post(
        f"/organizations/{tenants.b.id}/restore?confirm=true",
        content=data,
        headers={**tenants.a.headers["owner"], **ZIP},
    )

    assert response.status_code == 403
    assert await restore_run_events(session_factory) == []


async def test_restore_requires_confirmation(
    restore_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(restore_client, session_factory)
    data = await make_archive(session_factory, tenants.a.id)

    response = await restore_client.post(
        f"/organizations/{tenants.b.id}/restore",
        content=data,
        headers={**tenants.system, **ZIP},
    )

    assert response.status_code == 400
    assert "confirmed" in response.json()["error"]["message"]
    assert await restore_run_events(session_factory) == []


async def test_restore_refuses_non_empty_target(
    restore_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(restore_client, session_factory)
    data = await make_archive(session_factory, tenants.a.id)
    await add_source(session_factory, tenants.b.id, "Existing feed")

    response = await restore_client.post(
        f"/organizations/{tenants.b.id}/restore?confirm=true",
        content=data,
        headers={**tenants.system, **ZIP},
    )

    assert response.status_code == 400
    assert "must be empty" in response.json()["error"]["message"]
    async with session_factory() as session:
        restores = await session.scalar(select(OrganizationRestore.id))
    assert restores is None
    events = await restore_run_events(session_factory)
    assert len(events) == 1 and events[0].details == {"reason": "failed"}


async def test_restore_refuses_bad_user_mapping(
    restore_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(restore_client, session_factory)
    data = await make_archive(session_factory, tenants.a.id)
    unknown = uuid.uuid4()

    response = await restore_client.post(
        f"/organizations/{tenants.b.id}/restore?confirm=true&user_mapping={tenants.a.owner_id}:{unknown}",
        content=data,
        headers={**tenants.system, **ZIP},
    )

    assert response.status_code == 400
    assert "active user mapping" in response.json()["error"]["message"]


async def test_restore_refuses_corrupt_archive(
    restore_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(restore_client, session_factory)

    response = await restore_client.post(
        f"/organizations/{tenants.b.id}/restore?confirm=true",
        content=b"not a zip file",
        headers={**tenants.system, **ZIP},
    )

    assert response.status_code == 400
    events = await restore_run_events(session_factory)
    assert len(events) == 1 and events[0].details == {"reason": "failed"}


async def test_restore_plan_lists_user_mapping_suggestions(
    restore_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(restore_client, session_factory)
    data = await make_archive(session_factory, tenants.a.id)

    response = await restore_client.post(
        f"/organizations/{tenants.b.id}/restore-plan",
        content=data,
        headers={**tenants.system, **ZIP},
    )

    assert response.status_code == 200
    plan = response.json()
    assert plan["conflicts"] == []
    assert any(
        item["suggested_user_id"] == str(tenants.a.owner_id) and item["suggested_active"]
        for item in plan["user_mappings"]
    )
