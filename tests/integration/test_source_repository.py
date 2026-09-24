import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.sources.model import Source, SourceType
from signalscope.domain.sources.repository import SourceRepository

pytestmark = pytest.mark.anyio


async def add_source(
    session_factory: async_sessionmaker[AsyncSession], name: str, url: str | None = None
) -> Source:
    async with session_factory() as session:
        source = await SourceRepository(session).add(
            Source(type=SourceType.WEB, name=name, url=url)
        )
        await session.commit()
    return source


async def test_add_fills_in_database_values(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source = await SourceRepository(session).add(
            Source(type=SourceType.RSS, name="Example feed", url="https://example.com/rss")
        )

        assert isinstance(source.id, uuid.UUID)
        assert source.created_at is not None
        assert source.updated_at == source.created_at


async def test_get_returns_saved_source(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await add_source(session_factory, "Example site", "https://example.com")

    async with session_factory() as session:
        saved = await SourceRepository(session).get(source.id)

    assert saved is not None
    assert saved.type is SourceType.WEB
    assert saved.name == "Example site"
    assert saved.url == "https://example.com"
    assert saved.created_at == source.created_at


async def test_get_returns_none_for_unknown_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        assert await SourceRepository(session).get(uuid.uuid4()) is None


async def test_add_does_not_commit(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        source = await SourceRepository(session).add(Source(type=SourceType.UPLOAD, name="Uploads"))

    async with session_factory() as session:
        assert await SourceRepository(session).get(source.id) is None


async def test_list_all_returns_sources_in_creation_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_source(session_factory, "First")
    await add_source(session_factory, "Second")
    await add_source(session_factory, "Third")

    async with session_factory() as session:
        sources = await SourceRepository(session).list_all()

    assert [source.name for source in sources] == ["First", "Second", "Third"]


async def test_delete_removes_source(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await add_source(session_factory, "Old feed")

    async with session_factory() as session:
        deleted = await SourceRepository(session).delete(source.id)
        await session.commit()

    async with session_factory() as session:
        assert await SourceRepository(session).get(source.id) is None
    assert deleted is True


async def test_delete_returns_false_for_unknown_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        assert await SourceRepository(session).delete(uuid.uuid4()) is False
