import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.db.models import Base
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio


async def test_tables_start_empty(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        for table in Base.metadata.sorted_tables:
            count = await session.scalar(select(func.count()).select_from(table))
            assert count == 0, table.name


async def test_saved_rows_can_be_read_back(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        source = Source(type=SourceType.RSS, name="Example feed", url="https://example.com/rss")
        session.add(source)
        await session.commit()

    async with session_factory() as session:
        saved = await session.get(Source, source.id)

    assert saved is not None
    assert saved.type is SourceType.RSS
    assert saved.created_at.utcoffset() is not None
