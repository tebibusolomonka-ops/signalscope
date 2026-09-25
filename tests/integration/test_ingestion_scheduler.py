import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.ingestion.model import (
    IngestionJob,
    IngestionJobStatus,
    IngestionRun,
    IngestionStatus,
)
from signalscope.domain.ingestion.scheduler import IngestionScheduler, SchedulingResult
from signalscope.domain.sources.model import Source, SourceType
from signalscope.domain.sources.repository import SourceRepository

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 10, 7, tzinfo=UTC)


def scheduler(session_factory: async_sessionmaker[AsyncSession]) -> IngestionScheduler:
    return IngestionScheduler(session_factory, clock=lambda: NOW)


async def add_source(
    session_factory: async_sessionmaker[AsyncSession],
    name: str,
    next_ingestion_at: datetime | None,
    enabled: bool = True,
    interval: int = 60,
) -> Source:
    async with session_factory() as session:
        source = await SourceRepository(session).add(
            Source(
                type=SourceType.RSS,
                name=name,
                url="https://example.com/rss",
                ingestion_enabled=enabled,
                ingestion_interval_minutes=interval,
                next_ingestion_at=next_ingestion_at,
            )
        )
        await session.commit()
    return source


async def jobs(session_factory: async_sessionmaker[AsyncSession]) -> list[IngestionJob]:
    async with session_factory() as session:
        result = await session.scalars(select(IngestionJob).order_by(IngestionJob.created_at))
        return list(result.all())


async def next_time(session_factory: async_sessionmaker[AsyncSession], source: Source) -> datetime:
    async with session_factory() as session:
        saved = await SourceRepository(session).get(source.id)
    assert saved is not None
    assert saved.next_ingestion_at is not None
    return saved.next_ingestion_at


async def test_no_due_sources(session_factory: async_sessionmaker[AsyncSession]) -> None:
    result = await scheduler(session_factory).schedule_due(limit=10)

    assert result == SchedulingResult(sources_considered=0, jobs_created=0)
    assert await jobs(session_factory) == []


async def test_due_source_gets_a_run_and_a_job(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await add_source(session_factory, "Feed", datetime(2026, 5, 1, 10, 0, tzinfo=UTC))

    result = await scheduler(session_factory).schedule_due(limit=10)

    assert result == SchedulingResult(sources_considered=1, jobs_created=1)
    [job] = await jobs(session_factory)
    assert job.source_id == source.id
    assert job.status is IngestionJobStatus.PENDING
    assert job.available_at == NOW
    assert job.attempt_count == 0
    async with session_factory() as session:
        run = await session.get(IngestionRun, job.run_id)
    assert run is not None
    assert run.source_id == source.id
    assert run.status is IngestionStatus.PENDING


async def test_next_time_moves_forward_without_drift(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await add_source(session_factory, "Feed", datetime(2026, 5, 1, 10, 0, tzinfo=UTC))

    await scheduler(session_factory).schedule_due(limit=10)

    # Due at 10:00 and scheduled at 10:07, so the next time is 11:00.
    assert await next_time(session_factory, source) == datetime(2026, 5, 1, 11, 0, tzinfo=UTC)


async def test_late_source_skips_missed_times(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await add_source(session_factory, "Feed", NOW - timedelta(hours=5), interval=60)

    result = await scheduler(session_factory).schedule_due(limit=10)

    assert result.jobs_created == 1
    assert await next_time(session_factory, source) == datetime(2026, 5, 1, 11, 7, tzinfo=UTC)


async def test_many_due_sources(session_factory: async_sessionmaker[AsyncSession]) -> None:
    sources = [
        await add_source(session_factory, f"Feed {n}", NOW - timedelta(minutes=n)) for n in range(3)
    ]

    result = await scheduler(session_factory).schedule_due(limit=10)

    assert result == SchedulingResult(sources_considered=3, jobs_created=3)
    assert sorted(job.source_id for job in await jobs(session_factory)) == sorted(
        source.id for source in sources
    )


async def test_limit(session_factory: async_sessionmaker[AsyncSession]) -> None:
    waited_longest = await add_source(session_factory, "Oldest", NOW - timedelta(hours=2))
    await add_source(session_factory, "Newest", NOW - timedelta(minutes=1))
    waited_long = await add_source(session_factory, "Older", NOW - timedelta(hours=1))

    result = await scheduler(session_factory).schedule_due(limit=2)

    assert result == SchedulingResult(sources_considered=2, jobs_created=2)
    assert {job.source_id for job in await jobs(session_factory)} == {
        waited_longest.id,
        waited_long.id,
    }

    # The source left out is still due and is picked up next time.
    assert await scheduler(session_factory).schedule_due(limit=2) == SchedulingResult(
        sources_considered=1, jobs_created=1
    )


async def test_disabled_and_future_sources_are_ignored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_source(session_factory, "Disabled", NOW - timedelta(hours=1), enabled=False)
    await add_source(session_factory, "Future", NOW + timedelta(minutes=1))
    await add_source(session_factory, "No next time", None)

    result = await scheduler(session_factory).schedule_due(limit=10)

    assert result == SchedulingResult(sources_considered=0, jobs_created=0)
    assert await jobs(session_factory) == []


async def test_repeated_calls_do_not_queue_twice(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_source(session_factory, "Feed", NOW)

    first = await scheduler(session_factory).schedule_due(limit=10)
    second = await scheduler(session_factory).schedule_due(limit=10)

    assert first.jobs_created == 1
    assert second == SchedulingResult(sources_considered=0, jobs_created=0)
    assert len(await jobs(session_factory)) == 1


async def test_schedulers_running_at_the_same_time_queue_each_source_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    sources = [
        await add_source(session_factory, f"Feed {n}", NOW - timedelta(minutes=n)) for n in range(4)
    ]

    results = await asyncio.gather(
        *(scheduler(session_factory).schedule_due(limit=10) for _ in range(3))
    )

    assert sum(result.jobs_created for result in results) == 4
    queued = [job.source_id for job in await jobs(session_factory)]
    assert sorted(queued) == sorted(source.id for source in sources)


async def test_source_moved_forward_after_listing_is_skipped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await add_source(session_factory, "Feed", NOW)
    async with session_factory() as session:
        repository = SourceRepository(session)
        assert await repository.get_due_for_update(source.id, NOW) is not None
        locked = await repository.get_for_update(source.id)
        assert locked is not None
        locked.next_ingestion_at = NOW + timedelta(hours=1)
        await session.commit()

    async with session_factory() as session:
        assert await SourceRepository(session).get_due_for_update(source.id, NOW) is None


async def test_limit_must_be_positive(session_factory: async_sessionmaker[AsyncSession]) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        await scheduler(session_factory).schedule_due(limit=0)
