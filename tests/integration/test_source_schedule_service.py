import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.domain.sources.model import Source, SourceType
from signalscope.domain.sources.repository import SourceRepository
from signalscope.domain.sources.scheduling import SourceScheduleService

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def service(session: AsyncSession) -> SourceScheduleService:
    return SourceScheduleService(session, clock=lambda: NOW)


async def create_source(
    session_factory: async_sessionmaker[AsyncSession], source_type: SourceType = SourceType.RSS
) -> Source:
    async with session_factory() as session:
        source = await SourceRepository(session).add(
            Source(type=source_type, name="Example", url="https://example.com/rss")
        )
        await session.commit()
    return source


async def reload(session_factory: async_sessionmaker[AsyncSession], source: Source) -> Source:
    async with session_factory() as session:
        saved = await SourceRepository(session).get(source.id)
    assert saved is not None
    return saved


def schedule(source: Source) -> tuple[bool, int | None, datetime | None]:
    return source.ingestion_enabled, source.ingestion_interval_minutes, source.next_ingestion_at


async def test_enable_starts_now(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory)

    async with session_factory() as session:
        enabled = await service(session).enable(source.id, 60)

    assert schedule(enabled) == (True, 60, NOW)
    assert schedule(await reload(session_factory, source)) == (True, 60, NOW)


async def test_enable_with_a_start_time(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory)
    start_at = datetime(2026, 6, 1, 8, 30, tzinfo=timezone(timedelta(hours=2)))

    async with session_factory() as session:
        enabled = await service(session).enable(source.id, 30, start_at=start_at)

    expected = datetime(2026, 6, 1, 6, 30, tzinfo=UTC)
    assert schedule(enabled) == (True, 30, expected)
    assert enabled.next_ingestion_at is not None
    assert enabled.next_ingestion_at.tzinfo is UTC
    assert schedule(await reload(session_factory, source)) == (True, 30, expected)


async def test_enable_again_replaces_the_schedule(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory)

    async with session_factory() as session:
        await service(session).enable(source.id, 60)
    async with session_factory() as session:
        await service(session).enable(source.id, 15, start_at=NOW + timedelta(hours=1))

    assert schedule(await reload(session_factory, source)) == (
        True,
        15,
        NOW + timedelta(hours=1),
    )


@pytest.mark.parametrize("interval", [0, -5, 10081])
async def test_enable_rejects_invalid_intervals(
    session_factory: async_sessionmaker[AsyncSession], interval: int
) -> None:
    source = await create_source(session_factory)

    async with session_factory() as session:
        with pytest.raises(ValueError, match="interval_minutes"):
            await service(session).enable(source.id, interval)

    assert schedule(await reload(session_factory, source)) == (False, None, None)


async def test_enable_needs_a_time_zone(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory)

    async with session_factory() as session:
        with pytest.raises(ValueError, match="time zone"):
            await service(session).enable(source.id, 60, start_at=datetime(2026, 6, 1, 8, 30))


@pytest.mark.parametrize("source_type", [SourceType.UPLOAD, SourceType.API])
async def test_sources_without_a_fetching_adapter_cannot_be_scheduled(
    session_factory: async_sessionmaker[AsyncSession], source_type: SourceType
) -> None:
    source = await create_source(session_factory, source_type)

    async with session_factory() as session:
        with pytest.raises(ConflictError, match="cannot be ingested on a schedule"):
            await service(session).enable(source.id, 60)

    assert schedule(await reload(session_factory, source)) == (False, None, None)


async def test_disable_keeps_the_interval(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory)
    async with session_factory() as session:
        await service(session).enable(source.id, 60)

    async with session_factory() as session:
        disabled = await service(session).disable(source.id)

    assert schedule(disabled) == (False, 60, None)
    assert schedule(await reload(session_factory, source)) == (False, 60, None)


async def test_disable_a_source_that_was_never_scheduled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory)

    async with session_factory() as session:
        disabled = await service(session).disable(source.id)

    assert schedule(disabled) == (False, None, None)


async def test_unknown_source_is_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError, match="Source was not found."):
            await service(session).enable(uuid.uuid4(), 60)
        with pytest.raises(NotFoundError, match="Source was not found."):
            await service(session).disable(uuid.uuid4())
