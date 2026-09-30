import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from operations_helpers import user_by_email
from signalscope.core.errors import (
    ConflictError,
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
)
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.retention.service import AuditRetentionService
from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio

NOW = datetime.now(UTC)


def service(session: AsyncSession) -> AuditRetentionService:
    return AuditRetentionService(session, clock=lambda: NOW)


async def add_event(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID | None,
    days_ago: int,
    action: str = "organization.member_added",
) -> uuid.UUID:
    async with session_factory() as session:
        event = SecurityAuditEvent(
            organization_id=organization_id,
            action=action,
            resource_type="organization",
            created_at=NOW - timedelta(days=days_ago),
        )
        session.add(event)
        await session.commit()
        return event.id


async def remaining(
    session_factory: async_sessionmaker[AsyncSession], ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    async with session_factory() as session:
        found = await session.scalars(
            select(SecurityAuditEvent.id).where(SecurityAuditEvent.id.in_(ids))
        )
        return set(found.all())


async def test_without_a_policy_nothing_is_deleted(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    old = await add_event(session_factory, tenants.a.id, 4000)
    system = await user_by_email(session_factory, "system@example.org")

    async with session_factory() as session:
        policy = await service(session).get_policy(system, tenants.a.id)
        preview = await service(session).preview(system, tenants.a.id)
        with pytest.raises(ConflictError):
            await service(session).cleanup(system, tenants.a.id, 100)

    assert (policy.security_audit_days, policy.updated_at) == (None, None)
    assert (preview.retention_days, preview.cutoff, preview.eligible_count) == (None, None, 0)
    assert await remaining(session_factory, [old]) == {old}


async def test_cleanup_deletes_the_oldest_events_of_one_organization(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a, b = tenants.a, tenants.b
    oldest = await add_event(session_factory, a.id, 400)
    older = await add_event(session_factory, a.id, 300)
    old = await add_event(session_factory, a.id, 200)
    recent = await add_event(session_factory, a.id, 10)
    other = await add_event(session_factory, b.id, 400)
    without_organization = await add_event(session_factory, None, 400, "auth.login")
    system = await user_by_email(session_factory, "system@example.org")

    async with session_factory() as session:
        policy = await service(session).set_policy(system, a.id, 90)
    async with session_factory() as session:
        before = await service(session).preview(system, a.id)
    async with session_factory() as session:
        result = await service(session).cleanup(system, a.id, 2)
    async with session_factory() as session:
        after = await service(session).preview(system, a.id)
        cleanup_events = (
            await session.scalars(
                select(SecurityAuditEvent).where(
                    SecurityAuditEvent.action == "security.audit_retention_cleanup"
                )
            )
        ).all()

    assert policy.security_audit_days == 90
    assert policy.updated_at is not None
    assert (before.retention_days, before.eligible_count) == (90, 3)
    assert before.cutoff == NOW - timedelta(days=90)
    assert (result.deleted_count, result.retention_days) == (2, 90)
    ids = [oldest, older, old, recent, other, without_organization]
    assert await remaining(session_factory, ids) == {old, recent, other, without_organization}
    assert after.eligible_count == 1
    (event,) = cleanup_events
    assert event.organization_id == a.id
    assert event.actor_user_id == system.id
    assert event.details == {"deleted_count": 2, "retention_days": 90}


async def test_permissions(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a = tenants.a

    for role in ("owner", "admin"):
        user = await user_by_email(session_factory, f"a-{role}@example.org")
        async with session_factory() as session:
            await service(session).get_policy(user, a.id)
            await service(session).preview(user, a.id)
            with pytest.raises(ForbiddenError):
                await service(session).set_policy(user, a.id, 90)
            with pytest.raises(ForbiddenError):
                await service(session).cleanup(user, a.id, 10)
    for role in ("member", "viewer"):
        user = await user_by_email(session_factory, f"a-{role}@example.org")
        async with session_factory() as session:
            with pytest.raises(ForbiddenError):
                await service(session).preview(user, a.id)
    b_owner = await user_by_email(session_factory, "b-owner@example.org")
    async with session_factory() as session:
        with pytest.raises(NotFoundError):
            await service(session).get_policy(b_owner, a.id)
        with pytest.raises(NotFoundError):
            await service(session).get_policy(None, uuid.uuid4())
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(SecurityAuditEvent)
            .where(SecurityAuditEvent.action == "security.audit_retention_changed")
        )
    assert count == 0


async def test_bounds_and_the_local_command(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    old = await add_event(session_factory, tenants.a.id, 100)

    async with session_factory() as session:
        for days in (0, 29, 3651):
            with pytest.raises(InvalidInputError):
                await service(session).set_policy(None, tenants.a.id, days)
        await service(session).set_policy(None, tenants.a.id, 30)
    async with session_factory() as session:
        result = await service(session).cleanup(None, tenants.a.id, 10)
    async with session_factory() as session:
        cleared = await service(session).set_policy(None, tenants.a.id, None)

    assert result.deleted_count == 1
    assert await remaining(session_factory, [old]) == set()
    assert cleared.security_audit_days is None
