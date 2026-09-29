import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.organizations.model import Organization
from signalscope.domain.organizations.service import OrganizationService
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio


async def test_defaults(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        event = SecurityAuditEvent(action="auth.login", resource_type="user_session")
        session.add(event)
        await session.commit()

    assert event.created_at is not None
    assert event.details == {}
    assert (event.actor_user_id, event.organization_id, event.resource_id) == (None, None, None)


@pytest.mark.parametrize(
    ("action", "resource_type", "metadata"),
    [(" ", "user", "{}"), ("auth.login", "", "{}"), ("auth.login", "user", "[1]")],
    ids=["blank action", "blank resource type", "metadata not an object"],
)
async def test_checks(
    session_factory: async_sessionmaker[AsyncSession],
    action: str,
    resource_type: str,
    metadata: str,
) -> None:
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO security_audit_events (id, action, resource_type, metadata) "
                    "VALUES (gen_random_uuid(), :action, :resource_type, CAST(:metadata AS jsonb))"
                ),
                {"action": action, "resource_type": resource_type, "metadata": metadata},
            )


async def test_events_outlive_users_and_organizations(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner = await create_account(session_factory, "owner@example.org")
    leaver = await create_account(session_factory, "leaver@example.org")
    async with session_factory() as session:
        organization = await OrganizationService(session).create(owner, "Harbour", "harbour")
        session.add(
            SecurityAuditEvent(
                actor_user_id=leaver.id,
                organization_id=organization.id,
                action="organization.created",
                resource_type="organization",
                resource_id=organization.id,
                details={"role": "owner"},
            )
        )
        await session.commit()

    async with session_factory() as session:
        await session.execute(delete(User).where(User.id == leaver.id))
        await session.execute(delete(Organization).where(Organization.id == organization.id))
        await session.commit()
        event = await session.scalar(select(SecurityAuditEvent))

    assert event is not None
    assert (event.actor_user_id, event.organization_id) == (None, None)
    assert (event.resource_id, event.details) == (organization.id, {"role": "owner"})
