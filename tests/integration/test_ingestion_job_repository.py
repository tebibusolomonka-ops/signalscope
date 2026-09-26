import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import NotFoundError
from signalscope.domain.ingestion.job_repository import (
    IngestionJobRepository,
    InvalidJobStatusChangeError,
)
from signalscope.domain.ingestion.model import (
    IngestionJob,
    IngestionJobStatus,
    IngestionRun,
    IngestionStatus,
)
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
async def source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.RSS, name="Example", url="https://example.com/rss")
        session.add(source)
        await session.commit()
    return source


async def add_job(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    available_at: datetime = NOW,
    status: IngestionJobStatus = IngestionJobStatus.PENDING,
    job_id: uuid.UUID | None = None,
) -> IngestionJob:
    async with session_factory() as session:
        run = IngestionRun(source_id=source.id, status=IngestionStatus.PENDING)
        session.add(run)
        await session.flush()
        job = await IngestionJobRepository(session).add(
            IngestionJob(
                id=job_id or uuid.uuid4(),
                source_id=source.id,
                run_id=run.id,
                status=status,
                available_at=available_at,
            )
        )
        await session.commit()
    return job


async def claim(session_factory: async_sessionmaker[AsyncSession]) -> IngestionJob | None:
    async with session_factory() as session:
        job = await IngestionJobRepository(session).claim_next(NOW)
        await session.commit()
    return job


async def claim_token(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    job = await claim(session_factory)
    assert job is not None and job.lease_token is not None
    return job.lease_token


async def reload(
    session_factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID
) -> IngestionJob:
    async with session_factory() as session:
        job = await IngestionJobRepository(session).get(job_id)
    assert job is not None
    return job


async def test_add_and_get(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(session_factory, source)

    saved = await reload(session_factory, job.id)

    assert (saved.source_id, saved.run_id) == (source.id, job.run_id)
    assert saved.status is IngestionJobStatus.PENDING
    assert saved.available_at == NOW


async def test_get_returns_none_for_unknown_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        assert await IngestionJobRepository(session).get(uuid.uuid4()) is None


async def test_claim_without_jobs_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert await claim(session_factory) is None


async def test_claim_marks_the_job_running(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(session_factory, source, available_at=NOW - timedelta(minutes=5))

    claimed = await claim(session_factory)

    assert claimed is not None
    assert claimed.id == job.id
    saved = await reload(session_factory, job.id)
    assert saved.status is IngestionJobStatus.RUNNING
    assert saved.claimed_at == NOW
    assert saved.attempt_count == 1
    assert saved.finished_at is None


async def test_job_is_claimed_only_once(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    await add_job(session_factory, source)

    assert await claim(session_factory) is not None
    assert await claim(session_factory) is None


async def test_jobs_that_are_not_available_are_not_claimed(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    await add_job(session_factory, source, available_at=NOW + timedelta(seconds=1))
    for status in [
        IngestionJobStatus.RUNNING,
        IngestionJobStatus.COMPLETED,
        IngestionJobStatus.FAILED,
    ]:
        await add_job(session_factory, source, available_at=NOW - timedelta(hours=1), status=status)

    assert await claim(session_factory) is None


async def test_job_available_longest_is_claimed_first(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    newer = await add_job(session_factory, source, available_at=NOW - timedelta(minutes=1))
    older = await add_job(session_factory, source, available_at=NOW - timedelta(minutes=10))

    first, second = await claim(session_factory), await claim(session_factory)

    assert first is not None
    assert second is not None
    assert [first.id, second.id] == [older.id, newer.id]


async def test_jobs_available_at_the_same_time_are_claimed_in_creation_order(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    # The first job has the larger ID, so only created_at puts it first.
    ids = sorted([uuid.uuid4(), uuid.uuid4()], reverse=True)
    created = [await add_job(session_factory, source, job_id=job_id) for job_id in ids]

    claimed = [await claim(session_factory), await claim(session_factory)]

    assert [job.id for job in claimed if job is not None] == [job.id for job in created]


async def test_claim_is_not_committed(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(session_factory, source)

    async with session_factory() as session:
        assert await IngestionJobRepository(session).claim_next(NOW) is not None

    assert (await reload(session_factory, job.id)).status is IngestionJobStatus.PENDING


async def test_locked_job_is_skipped(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    first = await add_job(session_factory, source, available_at=NOW - timedelta(minutes=2))
    second = await add_job(session_factory, source, available_at=NOW - timedelta(minutes=1))

    async with (
        session_factory() as one,
        session_factory() as two,
        session_factory() as three,
    ):
        # Nothing is committed, so every claim still holds its row lock.
        claimed_by_one = await IngestionJobRepository(one).claim_next(NOW)
        claimed_by_two = await IngestionJobRepository(two).claim_next(NOW)
        claimed_by_three = await IngestionJobRepository(three).claim_next(NOW)

    assert claimed_by_one is not None
    assert claimed_by_two is not None
    assert (claimed_by_one.id, claimed_by_two.id) == (first.id, second.id)
    assert claimed_by_three is None


async def test_workers_claiming_at_the_same_time_get_different_jobs(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    jobs = [await add_job(session_factory, source) for _ in range(3)]

    claimed = await asyncio.gather(*(claim(session_factory) for _ in range(5)))

    claimed_ids = [job.id for job in claimed if job is not None]
    assert sorted(claimed_ids) == sorted(job.id for job in jobs)
    for job in jobs:
        assert (await reload(session_factory, job.id)).attempt_count == 1


async def test_mark_completed(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(session_factory, source)
    token = await claim_token(session_factory)
    finished_at = NOW + timedelta(minutes=3)

    async with session_factory() as session:
        await IngestionJobRepository(session).mark_completed(job.id, token, finished_at)
        await session.commit()

    saved = await reload(session_factory, job.id)
    assert saved.status is IngestionJobStatus.COMPLETED
    assert saved.finished_at == finished_at
    assert saved.last_error is None


async def test_mark_failed(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(session_factory, source)
    token = await claim_token(session_factory)

    async with session_factory() as session:
        await IngestionJobRepository(session).mark_failed(job.id, token, NOW, "  Feed went away.  ")
        await session.commit()

    saved = await reload(session_factory, job.id)
    assert saved.status is IngestionJobStatus.FAILED
    assert saved.finished_at == NOW
    assert saved.last_error == "Feed went away."


async def test_long_errors_are_shortened(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(session_factory, source)
    token = await claim_token(session_factory)

    async with session_factory() as session:
        failed = await IngestionJobRepository(session).mark_failed(job.id, token, NOW, "x" * 5000)
        await session.commit()

    assert failed.last_error is not None
    assert len(failed.last_error) == 1000
    assert failed.last_error.endswith("...")


async def test_only_running_jobs_can_finish(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    token = uuid.uuid4()
    job = await add_job(session_factory, source)

    async with session_factory() as session:
        with pytest.raises(InvalidJobStatusChangeError, match="is pending"):
            await IngestionJobRepository(session).mark_completed(job.id, token, NOW)

    token = await claim_token(session_factory)
    async with session_factory() as session:
        await IngestionJobRepository(session).mark_completed(job.id, token, NOW)
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(InvalidJobStatusChangeError, match="is completed"):
            await IngestionJobRepository(session).mark_failed(job.id, token, NOW, "Too late.")


async def test_finishing_unknown_job_is_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError, match="Ingestion job was not found."):
            await IngestionJobRepository(session).mark_completed(uuid.uuid4(), uuid.uuid4(), NOW)
