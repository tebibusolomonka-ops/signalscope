import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from operations_helpers import user_by_email
from signalscope.core.errors import ForbiddenError, InvalidInputError, NotFoundError
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.audit.retention_service import AuditRetentionService
from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)


async def add_event(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID | None,
    created_at: datetime,
    action: str = "auth.login",
) -> uuid.UUID:
    async with session_factory() as session:
        event = SecurityAuditEvent(
            actor_user_id=None,
            organization_id=organization_id,
            action=action,
            resource_type="organization",
            resource_id=organization_id,
            created_at=created_at,
        )
        session.add(event)
        await session.commit()
        return event.id


async def count_events(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID
) -> int:
    async with session_factory() as session:
        total = await session.scalar(
            select(func.count()).where(SecurityAuditEvent.organization_id == organization_id)
        )
    return total or 0


async def event_exists(
    session_factory: async_sessionmaker[AsyncSession], event_id: uuid.UUID
) -> bool:
    async with session_factory() as session:
        return await session.get(SecurityAuditEvent, event_id) is not None


async def cleaned_events(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID
) -> list[SecurityAuditEvent]:
    async with session_factory() as session:
        rows = await session.scalars(
            select(SecurityAuditEvent).where(
                SecurityAuditEvent.organization_id == organization_id,
                SecurityAuditEvent.action == "organization.security_audit_cleaned",
            )
        )
        return list(rows)


async def test_only_a_system_admin_sets_the_policy(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a = tenants.a

    async with session_factory() as session:
        by_system = AuditRetentionService(
            session, await user_by_email(session_factory, "system@example.org")
        )
        view = await by_system.set_policy(a.id, 90)
    assert view.security_audit_days == 90

    async with session_factory() as session:
        actor = await user_by_email(session_factory, "a-owner@example.org")
        with pytest.raises(ForbiddenError):
            await AuditRetentionService(session, actor).set_policy(a.id, 60)
    async with session_factory() as session:
        actor = await user_by_email(session_factory, "a-viewer@example.org")
        with pytest.raises(ForbiddenError):
            await AuditRetentionService(session, actor).set_policy(a.id, 60)
    async with session_factory() as session:
        actor = await user_by_email(session_factory, "outsider@example.org")
        with pytest.raises(NotFoundError):
            await AuditRetentionService(session, actor).set_policy(a.id, 60)

    # The policy is unchanged and one set was audited.
    async with session_factory() as session:
        actor = await user_by_email(session_factory, "a-owner@example.org")
        policy = await AuditRetentionService(session, actor).get_policy(a.id)
    assert policy.security_audit_days == 90
    async with session_factory() as session:
        events = await session.scalars(
            select(SecurityAuditEvent).where(
                SecurityAuditEvent.action == "organization.audit_retention_set"
            )
        )
        records = list(events)
    assert len(records) == 1
    assert records[0].details == {"retain_days": 90}


async def test_bounds_and_indefinite_retention(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    system = await user_by_email(session_factory, "system@example.org")

    async with session_factory() as session:
        with pytest.raises(InvalidInputError):
            await AuditRetentionService(session, system).set_policy(tenants.a.id, 10)
    async with session_factory() as session:
        with pytest.raises(InvalidInputError):
            await AuditRetentionService(session, system).set_policy(tenants.a.id, 4000)
    # None keeps events for ever.
    async with session_factory() as session:
        view = await AuditRetentionService(session, system).set_policy(tenants.a.id, None)
    assert view.security_audit_days is None


async def test_default_policy_is_indefinite(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    async with session_factory() as session:
        actor = await user_by_email(session_factory, "a-admin@example.org")
        policy = await AuditRetentionService(session, actor).get_policy(tenants.a.id)
    assert policy.security_audit_days is None


async def test_preview_counts_deletable_events(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a = tenants.a
    old = await add_event(session_factory, a.id, NOW - timedelta(days=100))
    await add_event(session_factory, a.id, NOW - timedelta(days=100))
    await add_event(session_factory, a.id, NOW - timedelta(days=10))
    system = await user_by_email(session_factory, "system@example.org")
    async with session_factory() as session:
        await AuditRetentionService(session, system).set_policy(a.id, 30)

    async with session_factory() as session:
        actor = await user_by_email(session_factory, "a-owner@example.org")
        preview = await AuditRetentionService(session, actor).preview(a.id, NOW)

    assert preview.security_audit_days == 30
    assert preview.cutoff == NOW - timedelta(days=30)
    assert preview.deletable_count == 2
    assert preview.total_count == await count_events(session_factory, a.id)
    assert await event_exists(session_factory, old)


async def test_indefinite_policy_previews_nothing_deletable(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a = tenants.a
    await add_event(session_factory, a.id, NOW - timedelta(days=5000))

    async with session_factory() as session:
        actor = await user_by_email(session_factory, "a-owner@example.org")
        preview = await AuditRetentionService(session, actor).preview(a.id, NOW)

    assert preview.cutoff is None
    assert preview.deletable_count == 0


async def test_cleanup_removes_old_events_bounded_and_audited(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a, b = tenants.a, tenants.b
    recent = await add_event(session_factory, a.id, NOW - timedelta(days=5))
    other_org = await add_event(session_factory, b.id, NOW - timedelta(days=500))
    no_org = await add_event(session_factory, None, NOW - timedelta(days=500))
    old_ids = [
        await add_event(session_factory, a.id, NOW - timedelta(days=200 + index))
        for index in range(4)
    ]
    system = await user_by_email(session_factory, "system@example.org")
    async with session_factory() as session:
        await AuditRetentionService(session, system).set_policy(a.id, 90)

    # A bounded run removes only the two oldest.
    async with session_factory() as session:
        first = await AuditRetentionService(session, system).cleanup(a.id, NOW, limit=2)
    assert first.deleted == 2

    async with session_factory() as session:
        second = await AuditRetentionService(session, system).cleanup(a.id, NOW, limit=100)
    assert second.deleted == 2

    async with session_factory() as session:
        third = await AuditRetentionService(session, system).cleanup(a.id, NOW, limit=100)
    assert third.deleted == 0

    for event_id in old_ids:
        assert not await event_exists(session_factory, event_id)
    # Recent events, other organizations and events with no organization are kept.
    assert await event_exists(session_factory, recent)
    assert await event_exists(session_factory, other_org)
    assert await event_exists(session_factory, no_org)
    # Each run that removed rows recorded one safe audit event.
    records = await cleaned_events(session_factory, a.id)
    assert sorted(record.details["deleted"] for record in records) == [2, 2]
    assert all(set(record.details) == {"deleted", "retain_days"} for record in records)


async def test_cleanup_needs_a_system_admin_and_a_server_context(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a = tenants.a
    old = await add_event(session_factory, a.id, NOW - timedelta(days=500))
    system = await user_by_email(session_factory, "system@example.org")
    async with session_factory() as session:
        await AuditRetentionService(session, system).set_policy(a.id, 90)

    async with session_factory() as session:
        owner = await user_by_email(session_factory, "a-owner@example.org")
        with pytest.raises(ForbiddenError):
            await AuditRetentionService(session, owner).cleanup(a.id, NOW, limit=100)
    assert await event_exists(session_factory, old)

    # The server context (no actor) may clean up.
    async with session_factory() as session:
        result = await AuditRetentionService(session, None).cleanup(a.id, NOW, limit=100)
    assert result.deleted == 1
    assert not await event_exists(session_factory, old)
