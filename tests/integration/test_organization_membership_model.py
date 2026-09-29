import uuid

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.domain.organizations.membership import OrganizationMembership, OrganizationRole
from signalscope.domain.organizations.model import Organization
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio


async def organization(
    session_factory: async_sessionmaker[AsyncSession], creator: uuid.UUID
) -> uuid.UUID:
    async with session_factory() as session:
        created = Organization(
            name="Harbour Watch", slug="harbour-watch", created_by_user_id=creator
        )
        session.add(created)
        await session.commit()
        return created.id


async def join(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    role: OrganizationRole = OrganizationRole.MEMBER,
) -> None:
    async with session_factory() as session:
        session.add(
            OrganizationMembership(organization_id=organization_id, user_id=user_id, role=role)
        )
        await session.commit()


async def test_every_role(session_factory: async_sessionmaker[AsyncSession]) -> None:
    owner = await create_account(session_factory, "owner@example.org")
    organization_id = await organization(session_factory, owner.id)

    for index, role in enumerate(OrganizationRole):
        user = await create_account(session_factory, f"user{index}@example.org")
        await join(session_factory, organization_id, user.id, role)

    async with session_factory() as session:
        roles = sorted(await session.scalars(select(OrganizationMembership.role)))
        stored = await session.scalar(select(OrganizationMembership).limit(1))
    assert roles == sorted(OrganizationRole)
    assert stored is not None and stored.created_at is not None


async def test_one_membership_per_user(session_factory: async_sessionmaker[AsyncSession]) -> None:
    user = await create_account(session_factory, "ana@example.org")
    organization_id = await organization(session_factory, user.id)
    await join(session_factory, organization_id, user.id)

    with pytest.raises(IntegrityError):
        await join(session_factory, organization_id, user.id, OrganizationRole.ADMIN)


async def test_unknown_role_is_rejected(session_factory: async_sessionmaker[AsyncSession]) -> None:
    user = await create_account(session_factory, "ana@example.org")
    organization_id = await organization(session_factory, user.id)

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO organization_memberships (organization_id, user_id, role) "
                    "VALUES (:organization, :user, 'guest')"
                ),
                {"organization": organization_id, "user": user.id},
            )


async def test_deleting_the_organization_deletes_memberships(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user = await create_account(session_factory, "ana@example.org")
    organization_id = await organization(session_factory, user.id)
    await join(session_factory, organization_id, user.id)

    async with session_factory() as session:
        await session.execute(delete(Organization).where(Organization.id == organization_id))
        await session.commit()
        assert list(await session.scalars(select(OrganizationMembership))) == []


async def test_a_member_cannot_be_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    creator = await create_account(session_factory, "owner@example.org")
    member = await create_account(session_factory, "ana@example.org")
    organization_id = await organization(session_factory, creator.id)
    await join(session_factory, organization_id, member.id)

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(delete(User).where(User.id == member.id))
