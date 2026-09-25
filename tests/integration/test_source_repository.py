import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.sources.model import MAX_INGESTION_INTERVAL_MINUTES, Source, SourceType
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


async def test_list_page_returns_sources_in_creation_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_source(session_factory, "First")
    await add_source(session_factory, "Second")
    await add_source(session_factory, "Third")

    async with session_factory() as session:
        sources = await SourceRepository(session).list_page(limit=10, offset=0)

    assert [source.name for source in sources] == ["First", "Second", "Third"]


async def test_list_page_applies_limit_and_offset(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    for name in ["A", "B", "C", "D", "E"]:
        await add_source(session_factory, name)

    async with session_factory() as session:
        repository = SourceRepository(session)
        middle = await repository.list_page(limit=2, offset=1)
        past_the_end = await repository.list_page(limit=2, offset=5)

    assert [source.name for source in middle] == ["B", "C"]
    assert past_the_end == []


async def test_count(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        assert await SourceRepository(session).count() == 0

    await add_source(session_factory, "First")
    await add_source(session_factory, "Second")

    async with session_factory() as session:
        assert await SourceRepository(session).count() == 2


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


async def test_new_sources_are_not_scheduled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await add_source(session_factory, "Example site")

    async with session_factory() as session:
        saved = await SourceRepository(session).get(source.id)

    assert saved is not None
    assert saved.ingestion_enabled is False
    assert saved.ingestion_interval_minutes is None
    assert saved.next_ingestion_at is None


async def test_database_turns_ingestion_off_by_default(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Plain SQL skips the model default, so this checks the column default.
    async with session_factory() as session:
        enabled = await session.scalar(
            text(
                "INSERT INTO sources (id, type, name) VALUES (:id, 'upload', 'Uploads') "
                "RETURNING ingestion_enabled"
            ),
            {"id": uuid.uuid4()},
        )

    assert enabled is False


@pytest.mark.parametrize(
    ("enabled", "interval"),
    [
        (False, 0),
        (False, -5),
        (False, MAX_INGESTION_INTERVAL_MINUTES + 1),
        (True, None),
    ],
)
async def test_invalid_schedule_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], enabled: bool, interval: int | None
) -> None:
    async with session_factory() as session:
        session.add(
            Source(
                type=SourceType.RSS,
                name="Example feed",
                url="https://example.com/rss",
                ingestion_enabled=enabled,
                ingestion_interval_minutes=interval,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.parametrize("interval", [1, MAX_INGESTION_INTERVAL_MINUTES])
async def test_interval_limits_are_allowed(
    session_factory: async_sessionmaker[AsyncSession], interval: int
) -> None:
    async with session_factory() as session:
        source = await SourceRepository(session).add(
            Source(
                type=SourceType.RSS,
                name="Example feed",
                url="https://example.com/rss",
                ingestion_enabled=True,
                ingestion_interval_minutes=interval,
            )
        )
        await session.commit()

    assert source.ingestion_interval_minutes == interval


async def test_next_ingestion_time_is_stored_with_its_time_zone(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    next_time = datetime(2026, 3, 1, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    async with session_factory() as session:
        source = await SourceRepository(session).add(
            Source(
                type=SourceType.RSS,
                name="Example feed",
                url="https://example.com/rss",
                ingestion_enabled=True,
                ingestion_interval_minutes=60,
                next_ingestion_at=next_time,
            )
        )
        await session.commit()

    async with session_factory() as session:
        saved = await SourceRepository(session).get(source.id)

    assert saved is not None
    assert saved.next_ingestion_at == next_time
    assert saved.next_ingestion_at == datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
