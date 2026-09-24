import uuid

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.model import Source, SourceType
from signalscope.domain.sources.schemas import SourceCreate
from signalscope.domain.sources.service import SourceService

pytestmark = pytest.mark.anyio


def rss_source(name: str) -> SourceCreate:
    return SourceCreate(type=SourceType.RSS, name=name, url="https://example.com/rss")


async def test_create_commits_source(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        created = await SourceService(session).create(rss_source("Example feed"))

    async with session_factory() as session:
        saved = await SourceService(session).get(created.id)

    assert saved.name == "Example feed"
    assert saved.url == "https://example.com/rss"


async def test_failed_create_rolls_back(session_factory: async_sessionmaker[AsyncSession]) -> None:
    # Skip validation so the database rejects the name instead.
    too_long = SourceCreate.model_construct(type=SourceType.UPLOAD, name="x" * 300, url=None)

    async with session_factory() as session:
        service = SourceService(session)
        with pytest.raises(DBAPIError):
            await service.create(too_long)

        assert await service.list_all() == []


async def test_get_unknown_source_raises_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError, match="Source was not found."):
            await SourceService(session).get(uuid.uuid4())


async def test_list_all_returns_created_sources(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        service = SourceService(session)
        await service.create(rss_source("First"))
        await service.create(rss_source("Second"))

        sources = await service.list_all()

    assert [source.name for source in sources] == ["First", "Second"]


async def test_delete_removes_source(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        created = await SourceService(session).create(rss_source("Old feed"))

    async with session_factory() as session:
        await SourceService(session).delete(created.id)

    async with session_factory() as session:
        with pytest.raises(NotFoundError):
            await SourceService(session).get(created.id)


async def test_delete_unknown_source_raises_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError, match="Source was not found."):
            await SourceService(session).delete(uuid.uuid4())


async def test_delete_source_with_documents_raises_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source = Source(type=SourceType.RSS, name="Busy feed", url="https://example.com/rss")
        session.add(source)
        await session.flush()
        session.add(Document(source_id=source.id, title="An article"))
        await session.commit()

    async with session_factory() as session:
        service = SourceService(session)
        with pytest.raises(ConflictError, match="Source has documents"):
            await service.delete(source.id)

        assert (await service.get(source.id)).name == "Busy feed"
