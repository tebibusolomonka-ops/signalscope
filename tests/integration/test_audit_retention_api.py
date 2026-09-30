import io
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.cli import cleanup_security_audit
from signalscope.core.settings import Settings
from signalscope.domain.audit.model import SecurityAuditEvent
from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio


async def add_old_events(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID, count: int
) -> None:
    async with session_factory() as session:
        for index in range(count):
            session.add(
                SecurityAuditEvent(
                    organization_id=organization_id,
                    action="organization.member_added",
                    resource_type="organization",
                    details={"role": "viewer"},
                    created_at=datetime.now(UTC) - timedelta(days=400 + index),
                )
            )
        await session.commit()


def base(organization_id: uuid.UUID) -> str:
    return f"/organizations/{organization_id}/retention"


async def test_retention_administration(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a = tenants.a
    await add_old_events(session_factory, a.id, 3)

    empty = await auth_client.get(base(a.id), headers=a.headers["admin"])
    assert empty.json() == {
        "organization_id": str(a.id),
        "security_audit_days": None,
        "updated_at": None,
    }
    for role in ("owner", "admin"):
        refused = await auth_client.put(
            base(a.id), json={"security_audit_days": 90}, headers=a.headers[role]
        )
        assert refused.status_code == 403
    set_policy = await auth_client.put(
        base(a.id), json={"security_audit_days": 90}, headers=tenants.system
    )
    assert set_policy.status_code == 200, set_policy.text
    assert set_policy.json()["security_audit_days"] == 90

    preview = await auth_client.get(f"{base(a.id)}/audit-preview", headers=a.headers["owner"])
    assert preview.status_code == 200
    assert (preview.json()["retention_days"], preview.json()["eligible_count"]) == (90, 3)

    owner_cleanup = await auth_client.post(
        f"{base(a.id)}/audit-cleanup",
        json={"limit": 10, "confirm": True},
        headers=a.headers["owner"],
    )
    unconfirmed = await auth_client.post(
        f"{base(a.id)}/audit-cleanup", json={"limit": 10}, headers=tenants.system
    )
    cleanup = await auth_client.post(
        f"{base(a.id)}/audit-cleanup", json={"limit": 2, "confirm": True}, headers=tenants.system
    )
    assert owner_cleanup.status_code == 403
    assert unconfirmed.status_code == 422
    assert cleanup.status_code == 200, cleanup.text
    assert cleanup.json()["deleted_count"] == 2
    left = await auth_client.get(f"{base(a.id)}/audit-preview", headers=a.headers["owner"])
    assert left.json()["eligible_count"] == 1

    audit = await auth_client.get(
        f"/security/audit?organization_id={a.id}&action=security.audit_retention_cleanup",
        headers=a.headers["owner"],
    )
    (event,) = audit.json()["items"]
    assert event["metadata"] == {"deleted_count": 2, "retention_days": 90}


async def test_refused_callers(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a, b = tenants.a, tenants.b

    member = await auth_client.get(base(a.id), headers=a.headers["member"])
    viewer = await auth_client.get(f"{base(a.id)}/audit-preview", headers=a.headers["viewer"])
    other = await auth_client.get(base(b.id), headers=a.headers["owner"])
    anonymous = await auth_client.get(base(a.id))
    no_policy = await auth_client.post(
        f"{base(a.id)}/audit-cleanup", json={"confirm": True}, headers=tenants.system
    )

    assert (member.status_code, viewer.status_code) == (403, 403)
    assert other.status_code == 404
    assert anonymous.status_code == 401
    assert no_policy.status_code == 409


async def test_command_previews_unless_told_to_apply(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    database_engine: AsyncEngine,
    migrated_database: Settings,
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a = tenants.a
    await add_old_events(session_factory, a.id, 2)
    await auth_client.put(base(a.id), json={"security_audit_days": 30}, headers=tenants.system)

    async def run(apply: bool) -> str:
        out, err = io.StringIO(), io.StringIO()
        code = await cleanup_security_audit(a.id, 100, migrated_database, out, err, apply=apply)
        assert (code, err.getvalue()) == (0, "")
        return out.getvalue()

    preview = await run(apply=False)
    applied = await run(apply=True)

    assert preview == (
        f"Organization: {a.id}\nRetention days: 30\nEligible: 2\n"
        "Deleted: 0 (preview only; add --apply to delete)\n"
    )
    assert applied == f"Organization: {a.id}\nRetention days: 30\nEligible: 2\nDeleted: 2\n"
    assert "viewer" not in preview + applied
    async with session_factory() as session:
        old = await session.scalars(
            select(SecurityAuditEvent).where(
                SecurityAuditEvent.organization_id == a.id,
                SecurityAuditEvent.action == "organization.member_added",
                SecurityAuditEvent.created_at < datetime.now(UTC) - timedelta(days=30),
            )
        )
    assert old.all() == []


@pytest.mark.parametrize(
    ("method", "path", "body", "field"),
    [
        ("PUT", "", {"security_audit_days": 29}, "security_audit_days"),
        ("PUT", "", {"security_audit_days": 3651}, "security_audit_days"),
        ("PUT", "", {}, "security_audit_days"),
        ("POST", "/audit-cleanup", {"limit": 0, "confirm": True}, "limit"),
        ("POST", "/audit-cleanup", {"confirm": "yes please"}, "confirm"),
    ],
)
async def test_bad_bodies_are_refused(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    method: str,
    path: str,
    body: dict[str, object],
    field: str,
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)

    response = await auth_client.request(
        method, f"{base(tenants.a.id)}{path}", json=body, headers=tenants.system
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["body", field]
