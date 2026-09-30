import io
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from operations_helpers import user_by_email
from signalscope.cli import cleanup_security_audit
from signalscope.core.settings import Settings
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.audit.retention_service import AuditRetentionService
from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)


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


async def org_event_count(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID
) -> int:
    async with session_factory() as session:
        total = await session.scalar(
            select(func.count()).where(SecurityAuditEvent.organization_id == organization_id)
        )
    return total or 0


async def set_policy(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID, days: int | None
) -> None:
    system = await user_by_email(session_factory, "system@example.org")
    async with session_factory() as session:
        await AuditRetentionService(session, system).set_policy(organization_id, days)


async def test_preview_then_apply(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    migrated_database: Settings,
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a, b = tenants.a, tenants.b
    for days in (200, 300, 5):
        await add_old_event(session_factory, a.id, days)
    await add_old_event(session_factory, b.id, 400)
    # Organization A keeps 90 days; organization B keeps events for ever.
    await set_policy(session_factory, a.id, 90)
    before = await org_event_count(session_factory, a.id)
    settings = Settings(database_url=migrated_database.database_url)

    out, err = io.StringIO(), io.StringIO()
    preview_code = await cleanup_security_audit(100, settings, out, err, clock=lambda: NOW)

    assert preview_code == 0
    assert "Organizations checked: 1" in out.getvalue()
    assert "Events over retention: 2" in out.getvalue()
    assert "Preview only" in out.getvalue()
    # Nothing was deleted by the preview.
    assert await org_event_count(session_factory, a.id) == before

    out, err = io.StringIO(), io.StringIO()
    apply_code = await cleanup_security_audit(
        100, settings, out, err, apply=True, clock=lambda: NOW
    )

    assert apply_code == 0
    assert "Events deleted: 2" in out.getvalue()
    # Two old events are gone, and the cleanup added one audit event of its own,
    # so the net change is minus one. The recent event and B's event stay.
    assert await org_event_count(session_factory, a.id) == before - 1
    assert await org_event_count(session_factory, b.id) >= 1
