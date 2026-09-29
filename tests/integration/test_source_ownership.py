import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.domain.organizations.model import Organization
from signalscope.domain.organizations.service import OrganizationService
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

FEED = "https://example.org/feed.xml"


async def organization(session_factory: async_sessionmaker[AsyncSession], slug: str) -> uuid.UUID:
    owner = await create_account(session_factory, f"{slug}@example.org")
    async with session_factory() as session:
        return (await OrganizationService(session).create(owner, slug.title(), slug)).id


async def add_source(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID | None
) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.RSS, name="Harbour feed", url=FEED)
        source.organization_id = organization_id
        session.add(source)
        await session.commit()
        return source


async def test_owned_and_legacy_sources(session_factory: async_sessionmaker[AsyncSession]) -> None:
    harbour = await organization(session_factory, "harbour")
    river = await organization(session_factory, "river")

    legacy = await add_source(session_factory, None)
    owned = await add_source(session_factory, harbour)
    # The same feed may be configured by another organization, and as legacy.
    other = await add_source(session_factory, river)
    await add_source(session_factory, None)

    async with session_factory() as session:
        owners = sorted(
            str(value) for value in await session.scalars(select(Source.organization_id))
        )
    assert legacy.organization_id is None
    assert (owned.organization_id, other.organization_id) == (harbour, river)
    assert owners == sorted([str(harbour), str(river), "None", "None"])


async def test_organization_must_exist(session_factory: async_sessionmaker[AsyncSession]) -> None:
    with pytest.raises(IntegrityError):
        await add_source(session_factory, uuid.uuid4())


async def test_organization_with_sources_cannot_be_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    harbour = await organization(session_factory, "harbour")
    await add_source(session_factory, harbour)

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(delete(Organization).where(Organization.id == harbour))
