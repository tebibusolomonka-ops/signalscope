import hashlib
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.leases import DEFAULT_LEASE_POLICY, LeasePolicy
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.model import Document
from signalscope.domain.processing.job_repository import DocumentProcessingJobRepository
from signalscope.domain.processing.model import DocumentProcessingJob, ProcessingJobStatus
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
async def source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.commit()
    return source


async def add_job(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    status: ProcessingJobStatus = ProcessingJobStatus.PENDING,
    lease_expires_at: datetime | None = None,
    last_error: str | None = None,
) -> DocumentProcessingJob:
    held = status is not ProcessingJobStatus.PENDING
    async with session_factory() as session:
        document = Document(source_id=source.id)
        session.add(document)
        await session.flush()
        asset = DocumentAsset(
            document_id=document.id,
            storage_key=f"ab/{uuid.uuid4().hex}",
            content_type="text/plain",
            size_bytes=5,
            sha256=hashlib.sha256(b"hello").hexdigest(),
        )
        session.add(asset)
        await session.flush()
        job = await DocumentProcessingJobRepository(session).add(
            DocumentProcessingJob(
                document_id=document.id,
                asset_id=asset.id,
                status=status,
                available_at=NOW - timedelta(hours=1),
                claimed_at=NOW - timedelta(minutes=10) if held else None,
                heartbeat_at=NOW - timedelta(minutes=6) if held else None,
                lease_expires_at=lease_expires_at,
                attempt_count=2 if held else 0,
                last_error=last_error,
            )
        )
        await session.commit()
    return job


async def reload(
    session_factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID
) -> DocumentProcessingJob:
    async with session_factory() as session:
        job = await DocumentProcessingJobRepository(session).get(job_id)
    assert job is not None
    return job


async def claim(
    session_factory: async_sessionmaker[AsyncSession],
    now: datetime = NOW,
    lease: LeasePolicy = DEFAULT_LEASE_POLICY,
) -> DocumentProcessingJob | None:
    async with session_factory() as session:
        job = await DocumentProcessingJobRepository(session).claim_next(now, lease)
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

    await claim(
        session_factory, now=datetime(2026, 5, 1, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    )

    saved = await reload(session_factory, job.id)
    assert saved.heartbeat_at == NOW
    assert saved.lease_expires_at == NOW + timedelta(minutes=5)


@pytest.mark.parametrize("status", [ProcessingJobStatus.COMPLETED, ProcessingJobStatus.FAILED])
async def test_finishing_ends_the_lease(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    status: ProcessingJobStatus,
) -> None:
    job = await add_job(session_factory, source)
    await claim(session_factory)

    async with session_factory() as session:
        repository = DocumentProcessingJobRepository(session)
        if status is ProcessingJobStatus.COMPLETED:
            await repository.mark_completed(job.id, NOW + timedelta(minutes=1))
        else:
            await repository.mark_failed(job.id, NOW + timedelta(minutes=1), "PDF is encrypted.")
        await session.commit()

    saved = await reload(session_factory, job.id)
    assert saved.lease_expires_at is None
    assert saved.heartbeat_at == NOW


async def recover(
    session_factory: async_sessionmaker[AsyncSession], limit: int = 10
) -> list[DocumentProcessingJob]:
    async with session_factory() as session:
        jobs = await DocumentProcessingJobRepository(session).recover_stale(NOW, limit)
        await session.commit()
    return jobs


async def test_expired_job_is_put_back_in_the_queue(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(
        session_factory,
        source,
        ProcessingJobStatus.RUNNING,
        lease_expires_at=NOW - timedelta(minutes=1),
        last_error="Stored file was not found.",
    )

    recovered = await recover(session_factory)

    assert [recovered_job.id for recovered_job in recovered] == [job.id]
    saved = await reload(session_factory, job.id)
    assert saved.status is ProcessingJobStatus.PENDING
    assert saved.available_at == NOW
    assert (saved.claimed_at, saved.heartbeat_at, saved.lease_expires_at) == (None, None, None)
    assert saved.attempt_count == 2
    assert saved.last_error == "Stored file was not found."


async def test_jobs_that_are_not_stale_are_left_alone(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    jobs = [
        await add_job(
            session_factory,
            source,
            ProcessingJobStatus.RUNNING,
            lease_expires_at=NOW + timedelta(seconds=1),
        ),
        await add_job(session_factory, source, ProcessingJobStatus.RUNNING),
        await add_job(session_factory, source, ProcessingJobStatus.PENDING),
        await add_job(
            session_factory,
            source,
            ProcessingJobStatus.COMPLETED,
            lease_expires_at=NOW - timedelta(hours=1),
        ),
        await add_job(
            session_factory,
            source,
            ProcessingJobStatus.FAILED,
            lease_expires_at=NOW - timedelta(hours=1),
        ),
    ]

    assert await recover(session_factory) == []
    for job in jobs:
        assert (await reload(session_factory, job.id)).status is job.status


async def test_recovery_is_limited(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    oldest = await add_job(
        session_factory,
        source,
        ProcessingJobStatus.RUNNING,
        lease_expires_at=NOW - timedelta(hours=1),
    )
    await add_job(
        session_factory,
        source,
        ProcessingJobStatus.RUNNING,
        lease_expires_at=NOW - timedelta(minutes=1),
    )

    assert [job.id for job in await recover(session_factory, limit=1)] == [oldest.id]
    assert len(await recover(session_factory, limit=5)) == 1


async def test_limit_must_be_positive(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        with pytest.raises(ValueError, match="at least 1"):
            await DocumentProcessingJobRepository(session).recover_stale(NOW, 0)


async def test_two_recoveries_do_not_take_the_same_job(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(
        session_factory,
        source,
        ProcessingJobStatus.RUNNING,
        lease_expires_at=NOW - timedelta(minutes=1),
    )

    async with session_factory() as one, session_factory() as two:
        # Nothing is committed yet, so the first recovery still holds the row lock.
        first = await DocumentProcessingJobRepository(one).recover_stale(NOW, 10)
        second = await DocumentProcessingJobRepository(two).recover_stale(NOW, 10)
        await one.commit()

    assert [recovered.id for recovered in first] == [job.id]
    assert second == []


async def test_recovered_job_can_be_claimed_again(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(
        session_factory,
        source,
        ProcessingJobStatus.RUNNING,
        lease_expires_at=NOW - timedelta(minutes=1),
    )
    await recover(session_factory)

    claimed = await claim(session_factory)

    assert claimed is not None
    assert (claimed.id, claimed.attempt_count) == (job.id, 3)


async def heartbeat(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    now: datetime,
    lease: LeasePolicy = DEFAULT_LEASE_POLICY,
) -> bool:
    async with session_factory() as session:
        extended = await DocumentProcessingJobRepository(session).heartbeat(job_id, now, lease)
        await session.commit()
    return extended


async def test_heartbeat_extends_the_lease(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(session_factory, source)
    await claim(session_factory)
    later = NOW + timedelta(minutes=4)

    assert await heartbeat(session_factory, job.id, later)

    saved = await reload(session_factory, job.id)
    assert (saved.heartbeat_at, saved.lease_expires_at) == (later, later + timedelta(minutes=5))
    assert saved.claimed_at == NOW


async def test_heartbeat_with_a_custom_lease(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(session_factory, source)
    await claim(session_factory)

    await heartbeat(session_factory, job.id, NOW, LeasePolicy(timedelta(minutes=30)))

    saved = await reload(session_factory, job.id)
    assert saved.lease_expires_at == NOW + timedelta(minutes=30)


async def test_heartbeat_keeps_the_job_from_being_recovered(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(
        session_factory,
        source,
        ProcessingJobStatus.RUNNING,
        lease_expires_at=NOW - timedelta(minutes=1),
    )

    assert await heartbeat(session_factory, job.id, NOW)

    assert await recover(session_factory) == []


@pytest.mark.parametrize(
    "status",
    [ProcessingJobStatus.PENDING, ProcessingJobStatus.COMPLETED, ProcessingJobStatus.FAILED],
)
async def test_heartbeat_needs_a_running_job(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    status: ProcessingJobStatus,
) -> None:
    job = await add_job(session_factory, source, status)

    assert not await heartbeat(session_factory, job.id, NOW)

    saved = await reload(session_factory, job.id)
    assert (saved.heartbeat_at, saved.lease_expires_at) == (job.heartbeat_at, None)


async def test_heartbeat_for_an_unknown_job(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert not await heartbeat(session_factory, uuid.uuid4(), NOW)
