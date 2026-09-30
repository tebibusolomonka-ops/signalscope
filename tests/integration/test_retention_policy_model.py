import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.domain.organizations.model import Organization
from signalscope.domain.retention.model import OrganizationRetentionPolicy

pytestmark = pytest.mark.anyio


async def add_organization(session_factory: async_sessionmaker[AsyncSession]) -> Organization:
    owner = await create_account(session_factory, "owner@example.org")
    async with session_factory() as session:
        organization = Organization(name="Harbour", slug="harbour", created_by_user_id=owner.id)
        session.add(organization)
        await session.commit()
    return organization


async def test_policy_defaults_to_keeping_everything(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization = await add_organization(session_factory)
    async with session_factory() as session:
        policy = OrganizationRetentionPolicy(organization_id=organization.id)
        session.add(policy)
        await session.commit()

    assert policy.security_audit_days is None
    assert policy.created_at is not None
    assert policy.updated_at >= policy.created_at


@pytest.mark.parametrize("days", [30, 365, 3650])
async def test_days_within_range(
    session_factory: async_sessionmaker[AsyncSession], days: int
) -> None:
    organization = await add_organization(session_factory)
    async with session_factory() as session:
        session.add(
            OrganizationRetentionPolicy(organization_id=organization.id, security_audit_days=days)
        )
        await session.commit()


@pytest.mark.parametrize("days", [0, 29, 3651, -5])
async def test_days_outside_range(
    session_factory: async_sessionmaker[AsyncSession], days: int
) -> None:
    organization = await add_organization(session_factory)
    async with session_factory() as session:
        session.add(
            OrganizationRetentionPolicy(organization_id=organization.id, security_audit_days=days)
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_one_policy_per_organization_and_cascade(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization = await add_organization(session_factory)
    async with session_factory() as session:
        session.add(OrganizationRetentionPolicy(organization_id=organization.id))
        await session.commit()
    async with session_factory() as session:
        session.add(
            OrganizationRetentionPolicy(organization_id=organization.id, security_audit_days=90)
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    async with session_factory() as session:
        await session.execute(delete(Organization).where(Organization.id == organization.id))
        await session.commit()
        remaining = (await session.scalars(select(OrganizationRetentionPolicy))).all()
    assert remaining == []
