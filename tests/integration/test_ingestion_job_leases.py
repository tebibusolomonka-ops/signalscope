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
