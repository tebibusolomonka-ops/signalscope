import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.leases import DEFAULT_LEASE_POLICY, LeasePolicy
from signalscope.domain.ingestion.job_repository import IngestionJobRepository
from signalscope.domain.ingestion.model import (
    IngestionJob,
    IngestionJobStatus,
    IngestionRun,
    IngestionStatus,
)
from signalscope.domain.ingestion.recovery import (
    STOPPED_WORKER_ERROR,
    recover_stale_ingestion_jobs,
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
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> IngestionJob:
    async with session_factory() as session:
        run = IngestionRun(source_id=source.id, status=IngestionStatus.PENDING)
        session.add(run)
        await session.flush()
        job = await IngestionJobRepository(session).add(
            IngestionJob(source_id=source.id, run_id=run.id, available_at=NOW)
        )
        await session.commit()
    return job


async def reload(
    session_factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID
) -> IngestionJob:
    async with session_factory() as session:
        job = await IngestionJobRepository(session).get(job_id)
    assert job is not None
    return job


async def claim(
    session_factory: async_sessionmaker[AsyncSession],
    now: datetime = NOW,
    lease: LeasePolicy = DEFAULT_LEASE_POLICY,
) -> IngestionJob | None:
    async with session_factory() as session:
        job = await IngestionJobRepository(session).claim_next(now, lease)
        await session.commit()
    return job


async def test_new_job_has_no_lease(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(session_factory, source)

    saved = await reload(session_factory, job.id)

    assert (saved.heartbeat_at, saved.lease_expires_at) == (None, None)


async def test_claim_starts_a_lease(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(session_factory, source)

    await claim(session_factory)

    saved = await reload(session_factory, job.id)
    assert saved.claimed_at == NOW
    assert saved.heartbeat_at == NOW
    assert saved.lease_expires_at == NOW + timedelta(minutes=5)


async def test_claim_with_a_custom_lease(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(session_factory, source)

    await claim(session_factory, lease=LeasePolicy(timedelta(seconds=30)))

    assert (await reload(session_factory, job.id)).lease_expires_at == NOW + timedelta(seconds=30)


async def test_lease_times_keep_the_instant(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(session_factory, source)
    local_now = datetime(2026, 5, 1, 14, 0, tzinfo=timezone(timedelta(hours=2)))

    await claim(session_factory, now=local_now)

    saved = await reload(session_factory, job.id)
    assert saved.heartbeat_at == NOW
    assert saved.lease_expires_at == NOW + timedelta(minutes=5)
    assert saved.lease_expires_at is not None
    assert saved.lease_expires_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize("status", [IngestionJobStatus.COMPLETED, IngestionJobStatus.FAILED])
async def test_finishing_ends_the_lease(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    status: IngestionJobStatus,
) -> None:
    job = await add_job(session_factory, source)
    await claim(session_factory)

    async with session_factory() as session:
        repository = IngestionJobRepository(session)
        if status is IngestionJobStatus.COMPLETED:
            await repository.mark_completed(job.id, NOW + timedelta(minutes=1))
        else:
            await repository.mark_failed(job.id, NOW + timedelta(minutes=1), "Feed went away.")
        await session.commit()

    saved = await reload(session_factory, job.id)
    assert saved.lease_expires_at is None
    assert saved.heartbeat_at == NOW


async def add_held_job(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    status: IngestionJobStatus = IngestionJobStatus.RUNNING,
    lease_expires_at: datetime | None = NOW - timedelta(minutes=1),
    run_status: IngestionStatus = IngestionStatus.RUNNING,
    last_error: str | None = None,
) -> IngestionJob:
    async with session_factory() as session:
        run = IngestionRun(source_id=source.id, status=run_status)
        session.add(run)
        await session.flush()
        job = await IngestionJobRepository(session).add(
            IngestionJob(
                source_id=source.id,
                run_id=run.id,
                status=status,
                available_at=NOW - timedelta(hours=1),
                claimed_at=NOW - timedelta(minutes=10),
                heartbeat_at=NOW - timedelta(minutes=6),
                lease_expires_at=lease_expires_at,
                attempt_count=2,
                last_error=last_error,
            )
        )
        await session.commit()
    return job


async def recover(
    session_factory: async_sessionmaker[AsyncSession], limit: int = 10
) -> list[IngestionJob]:
    async with session_factory() as session:
        jobs = await IngestionJobRepository(session).recover_stale(NOW, limit)
        await session.commit()
    return jobs


async def test_expired_job_is_put_back_in_the_queue(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_held_job(session_factory, source, last_error="Request timed out.")

    recovered = await recover(session_factory)

    assert [recovered_job.id for recovered_job in recovered] == [job.id]
    saved = await reload(session_factory, job.id)
    assert saved.status is IngestionJobStatus.PENDING
    assert saved.available_at == NOW
    assert (saved.claimed_at, saved.heartbeat_at, saved.lease_expires_at) == (None, None, None)
    assert saved.attempt_count == 2
    assert saved.last_error == "Request timed out."


async def test_lease_ending_exactly_now_is_expired(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_held_job(session_factory, source, lease_expires_at=NOW)

    assert [recovered.id for recovered in await recover(session_factory)] == [job.id]


async def test_jobs_that_are_not_stale_are_left_alone(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    future = await add_held_job(
        session_factory, source, lease_expires_at=NOW + timedelta(seconds=1)
    )
    no_lease = await add_held_job(session_factory, source, lease_expires_at=None)
    others = [
        await add_held_job(session_factory, source, status=status)
        for status in [
            IngestionJobStatus.PENDING,
            IngestionJobStatus.COMPLETED,
            IngestionJobStatus.FAILED,
        ]
    ]

    assert await recover(session_factory) == []
    for job in [future, no_lease, *others]:
        saved = await reload(session_factory, job.id)
        assert saved.status is job.status
        assert saved.lease_expires_at == job.lease_expires_at


async def test_recovery_is_limited(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    oldest = await add_held_job(session_factory, source, lease_expires_at=NOW - timedelta(hours=1))
    await add_held_job(session_factory, source, lease_expires_at=NOW - timedelta(minutes=1))

    recovered = await recover(session_factory, limit=1)

    assert [job.id for job in recovered] == [oldest.id]
    assert len(await recover(session_factory, limit=5)) == 1


async def test_limit_must_be_positive(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        with pytest.raises(ValueError, match="at least 1"):
            await IngestionJobRepository(session).recover_stale(NOW, 0)


async def test_two_recoveries_do_not_take_the_same_job(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_held_job(session_factory, source)

    async with session_factory() as one, session_factory() as two:
        # Nothing is committed yet, so the first recovery still holds the row lock.
        first = await IngestionJobRepository(one).recover_stale(NOW, 10)
        second = await IngestionJobRepository(two).recover_stale(NOW, 10)
        await one.commit()

    assert [recovered.id for recovered in first] == [job.id]
    assert second == []


async def test_recovered_job_can_be_claimed_again(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_held_job(session_factory, source)
    await recover(session_factory)

    claimed = await claim(session_factory)

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.attempt_count == 3


async def test_service_gives_a_started_job_a_new_run(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_held_job(session_factory, source)

    [recovered] = await recover_stale_ingestion_jobs(session_factory, NOW, 10)

    saved = await reload(session_factory, job.id)
    assert saved.status is IngestionJobStatus.PENDING
    assert saved.run_id != job.run_id
    assert recovered.run_id == saved.run_id
    async with session_factory() as session:
        old_run = await session.get(IngestionRun, job.run_id)
        new_run = await session.get(IngestionRun, saved.run_id)
    assert old_run is not None
    assert new_run is not None
    assert old_run.status is IngestionStatus.FAILED
    assert old_run.error_message == STOPPED_WORKER_ERROR
    assert old_run.finished_at == NOW
    assert new_run.status is IngestionStatus.PENDING
    assert new_run.source_id == source.id


async def test_service_keeps_a_run_that_never_started(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_held_job(session_factory, source, run_status=IngestionStatus.PENDING)

    await recover_stale_ingestion_jobs(session_factory, NOW, 10)

    assert (await reload(session_factory, job.id)).run_id == job.run_id
