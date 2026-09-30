import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.audit.model import SecurityAuditEvent
from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio

NOW = datetime.now(UTC)


def path(suffix: str, organization_id: uuid.UUID) -> str:
    return f"/security/audit/retention{suffix}?organization_id={organization_id}"


async def add_old_event(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID, days: int
) -> None:
    async with session_factory() as session:
        session.add(
            SecurityAuditEvent(
                organization_id=organization_id,
                action="auth.login",
                resource_type="organization",
                resource_id=organization_id,
                created_at=NOW - timedelta(days=days),
            )
        )
        await session.commit()


async def test_read_and_set_policy(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a = tenants.a

    default = await auth_client.get(path("", a.id), headers=a.headers["owner"])
    assert default.status_code == 200
    assert default.json() == {"organization_id": str(a.id), "security_audit_days": None}

    # Only a system admin may set the policy.
    denied = await auth_client.put(
        path("", a.id), json={"security_audit_days": 90}, headers=a.headers["owner"]
    )
    assert denied.status_code == 403
    set_ok = await auth_client.put(
        path("", a.id), json={"security_audit_days": 90}, headers=tenants.system
    )
    assert set_ok.status_code == 200
    assert set_ok.json()["security_audit_days"] == 90

    # Owners and admins may still read it.
    seen = await auth_client.get(path("", a.id), headers=a.headers["admin"])
    assert seen.json()["security_audit_days"] == 90


async def test_policy_bounds_and_indefinite(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a = tenants.a

    too_small = await auth_client.put(
        path("", a.id), json={"security_audit_days": 10}, headers=tenants.system
    )
    too_large = await auth_client.put(
        path("", a.id), json={"security_audit_days": 4000}, headers=tenants.system
    )
    forever = await auth_client.put(
        path("", a.id), json={"security_audit_days": None}, headers=tenants.system
    )

    assert (too_small.status_code, too_large.status_code) == (422, 422)
    assert forever.status_code == 200
    assert forever.json()["security_audit_days"] is None


async def test_refused_callers(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a, b = tenants.a, tenants.b

    member = await auth_client.get(path("", a.id), headers=a.headers["member"])
    viewer = await auth_client.get(path("", a.id), headers=a.headers["viewer"])
    other = await auth_client.get(path("", b.id), headers=a.headers["owner"])
    anonymous = await auth_client.get(path("", a.id))

    assert (member.status_code, viewer.status_code) == (403, 403)
    assert other.status_code == 404
    assert anonymous.status_code == 401


async def test_preview_and_cleanup(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a = tenants.a
    for days in (200, 300, 5):
        await add_old_event(session_factory, a.id, days)
    await auth_client.put(path("", a.id), json={"security_audit_days": 90}, headers=tenants.system)

    preview = await auth_client.get(path("/preview", a.id), headers=a.headers["admin"])
    assert preview.status_code == 200
    assert preview.json()["deletable_count"] == 2
    assert preview.json()["cutoff"] is not None

    # Owners cannot run the cleanup; system admins can.
    denied = await auth_client.post(path("/cleanup", a.id), json={}, headers=a.headers["owner"])
    assert denied.status_code == 403
    cleaned = await auth_client.post(
        path("/cleanup", a.id), json={"limit": 100}, headers=tenants.system
    )
    assert cleaned.status_code == 200
    assert cleaned.json()["deleted"] == 2

    after = await auth_client.get(path("/preview", a.id), headers=a.headers["admin"])
    assert after.json()["deletable_count"] == 0
