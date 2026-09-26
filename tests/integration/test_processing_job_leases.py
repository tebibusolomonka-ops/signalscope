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
