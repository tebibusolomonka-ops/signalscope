import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.domain.audit.retention import OrganizationAuditRetentionPolicy
from signalscope.domain.organizations.model import Organization
from signalscope.domain.organizations.service import OrganizationService

pytestmark = pytest.mark.anyio


async def make_organization(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    owner = await create_account(session_factory, "owner@example.org")
    async with session_factory() as session:
        organization = await OrganizationService(session).create(owner, "Org", "org")
        return organization.id


async def add_policy(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID,
    days: int | None,
) -> None:
    async with session_factory() as session:
        session.add(
            OrganizationAuditRetentionPolicy(
                organization_id=organization_id, security_audit_days=days
            )
        )
        await session.commit()


@pytest.mark.parametrize("days", [None, 30, 365, 3650])
async def test_a_policy_stores_days_within_the_bounds(
    session_factory: async_sessionmaker[AsyncSession], days: int | None
) -> None:
    organization_id = await make_organization(session_factory)

    await add_policy(session_factory, organization_id, days)

    async with session_factory() as session:
        policy = await session.get(OrganizationAuditRetentionPolicy, organization_id)
    assert policy is not None
    assert policy.security_audit_days == days


@pytest.mark.parametrize("days", [0, 29, 3651])
async def test_days_outside_the_bounds_are_refused(
    session_factory: async_sessionmaker[AsyncSession], days: int
) -> None:
    organization_id = await make_organization(session_factory)

    with pytest.raises(IntegrityError):
        await add_policy(session_factory, organization_id, days)


async def test_one_policy_per_organization(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_id = await make_organization(session_factory)
    await add_policy(session_factory, organization_id, 30)

    with pytest.raises(IntegrityError):
        await add_policy(session_factory, organization_id, 90)


async def test_deleting_the_organization_removes_its_policy(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_id = await make_organization(session_factory)
    await add_policy(session_factory, organization_id, 30)

    async with session_factory() as session:
        organization = await session.get(Organization, organization_id)
        assert organization is not None
        await session.delete(organization)
        await session.commit()

    async with session_factory() as session:
        assert await session.get(OrganizationAuditRetentionPolicy, organization_id) is None
