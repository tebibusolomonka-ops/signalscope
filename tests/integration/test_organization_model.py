import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.domain.organizations.model import Organization
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio


async def add(
    session_factory: async_sessionmaker[AsyncSession], slug: str, creator: uuid.UUID
) -> Organization:
    async with session_factory() as session:
        organization = Organization(name="Harbour Watch", slug=slug, created_by_user_id=creator)
        session.add(organization)
        await session.commit()
        return organization


async def test_organization_is_stored(session_factory: async_sessionmaker[AsyncSession]) -> None:
    user = await create_account(session_factory, "ana@example.org")

    organization = await add(session_factory, "harbour-watch", user.id)

    async with session_factory() as session:
        stored = await session.get(Organization, organization.id)
    assert stored is not None
    assert (stored.name, stored.slug, stored.created_by_user_id) == (
        "Harbour Watch",
        "harbour-watch",
        user.id,
    )
    assert stored.created_at is not None and stored.updated_at is not None


async def test_slug_is_unique(session_factory: async_sessionmaker[AsyncSession]) -> None:
    user = await create_account(session_factory, "ana@example.org")
    await add(session_factory, "harbour-watch", user.id)

    with pytest.raises(IntegrityError):
        await add(session_factory, "harbour-watch", user.id)


@pytest.mark.parametrize("slug", ["Harbour", "-harbour", "harbour--watch"])
async def test_database_checks_the_slug(
    session_factory: async_sessionmaker[AsyncSession], slug: str
) -> None:
    user = await create_account(session_factory, "ana@example.org")

    with pytest.raises(IntegrityError):
        await add(session_factory, slug, user.id)


async def test_creator_must_exist_and_stays(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(IntegrityError):
        await add(session_factory, "nobody", uuid.uuid4())

    user = await create_account(session_factory, "ana@example.org")
    await add(session_factory, "harbour-watch", user.id)
    async with session_factory() as session:
        # RESTRICT fails at once, when the row is deleted.
        with pytest.raises(IntegrityError):
            await session.execute(delete(User).where(User.id == user.id))
