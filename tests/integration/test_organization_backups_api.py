import dataclasses
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
from tenancy_helpers import make_tenants

pytestmark = pytest.mark.anyio


@pytest.fixture
async def backup_client(
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


async def test_policy_manual_run_list_and_audit(
    backup_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(backup_client, session_factory)
    base = f"/organizations/{tenants.a.id}"

    default = await backup_client.get(f"{base}/backup-policy", headers=tenants.a.headers["owner"])
    assert default.status_code == 200
    assert default.json() == {
        "organization_id": str(tenants.a.id),
        "enabled": False,
        "frequency": "daily",
        "retention_count": 7,
        "include_assets": False,
        "last_run_at": None,
        "next_run_at": None,
        "updated_at": None,
    }

    updated = await backup_client.put(
        f"{base}/backup-policy",
        headers=tenants.a.headers["admin"],
        json={
            "enabled": True,
            "frequency": "weekly",
            "retention_count": 3,
            "include_assets": False,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["next_run_at"] is not None

    run = await backup_client.post(f"{base}/backups/run", headers=tenants.system)
    assert run.status_code == 201, run.text
    assert run.json()["status"] == OrganizationExportStatus.COMPLETED
    listed = await backup_client.get(f"{base}/backups", headers=tenants.a.headers["owner"])
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [run.json()["id"]]

    async with session_factory() as session:
        actions = list(
            await session.scalars(
                select(SecurityAuditEvent.action).where(
                    SecurityAuditEvent.organization_id == tenants.a.id,
                    SecurityAuditEvent.action.in_(
                        ["organization.backup_policy_changed", "organization.backup_run"]
                    ),
                )
            )
        )
    assert set(actions) == {"organization.backup_policy_changed", "organization.backup_run"}


@pytest.mark.parametrize("role", ["member", "viewer"])
async def test_non_admin_members_cannot_manage_backups(
    backup_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    role: str,
) -> None:
    tenants = await make_tenants(backup_client, session_factory)
    response = await backup_client.get(
        f"/organizations/{tenants.a.id}/backups", headers=tenants.a.headers[role]
    )
    assert response.status_code == 403
