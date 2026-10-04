import dataclasses
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from password_helpers import fast_hasher
from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.core.settings import Settings
from signalscope.domain.audit.model import SecurityAuditEvent
from tenancy_helpers import add_document, add_source, make_tenants

pytestmark = pytest.mark.anyio


@pytest.fixture
async def drill_client(
    migrated_database: Settings, tmp_path: Path
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


async def seed_source_org(
    session_factory: async_sessionmaker[AsyncSession], organization_id: object
) -> None:
    source_id = await add_source(session_factory, organization_id, "Drill source")
    await add_document(session_factory, source_id, "Drill doc", ["Harbour rose."])


async def drill_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[SecurityAuditEvent]:
    async with session_factory() as session:
        return list(
            await session.scalars(
                select(SecurityAuditEvent).where(
                    SecurityAuditEvent.action == "organization.disaster_recovery_drill_run"
                )
            )
        )


async def test_owner_runs_verification_drill_with_audit(
    drill_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(drill_client, session_factory)
    await seed_source_org(session_factory, tenants.a.id)

    response = await drill_client.post(
        f"/organizations/{tenants.a.id}/drills",
        json={"mode": "verification_only"},
        headers=tenants.a.headers["owner"],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["mode"] == "verification_only"
    assert body["status"] == "completed"

    listed = await drill_client.get(
        f"/organizations/{tenants.a.id}/drills", headers=tenants.a.headers["admin"]
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    detail = await drill_client.get(
        f"/organizations/{tenants.a.id}/drills/{body['id']}", headers=tenants.a.headers["owner"]
    )
    assert detail.status_code == 200

    events = await drill_events(session_factory)
    reasons = sorted(event.details["reason"] for event in events)
    assert reasons == ["completed", "started"]


async def test_member_cannot_run_drill(
    drill_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(drill_client, session_factory)
    await seed_source_org(session_factory, tenants.a.id)

    response = await drill_client.post(
        f"/organizations/{tenants.a.id}/drills",
        json={"mode": "verification_only"},
        headers=tenants.a.headers["member"],
    )

    assert response.status_code == 403


async def test_restore_test_requires_system_admin(
    drill_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(drill_client, session_factory)
    await seed_source_org(session_factory, tenants.a.id)

    denied = await drill_client.post(
        f"/organizations/{tenants.a.id}/drills",
        json={"mode": "restore_test", "target_organization_id": str(tenants.b.id)},
        headers=tenants.a.headers["admin"],
    )
    assert denied.status_code == 403

    allowed = await drill_client.post(
        f"/organizations/{tenants.a.id}/drills",
        json={"mode": "restore_test", "target_organization_id": str(tenants.b.id)},
        headers=tenants.system,
    )
    assert allowed.status_code == 201
    assert allowed.json()["status"] == "completed"


async def test_restore_test_without_target_is_rejected(
    drill_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(drill_client, session_factory)
    await seed_source_org(session_factory, tenants.a.id)

    response = await drill_client.post(
        f"/organizations/{tenants.a.id}/drills",
        json={"mode": "restore_test"},
        headers=tenants.system,
    )

    assert response.status_code == 422
