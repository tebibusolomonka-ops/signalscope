import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import NotFoundError
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.model import Document
from signalscope.domain.processing.job_repository import (
    DocumentProcessingJobRepository,
    InvalidProcessingJobStatusChangeError,
)
from signalscope.domain.processing.model import DocumentProcessingJob, ProcessingJobStatus
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
async def source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Uploads")
        session.add(source)
        await session.commit()
    return source


async def add_job(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    available_at: datetime = NOW,
    status: ProcessingJobStatus = ProcessingJobStatus.PENDING,
    job_id: uuid.UUID | None = None,
) -> DocumentProcessingJob:
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
                id=job_id or uuid.uuid4(),
                document_id=document.id,
                asset_id=asset.id,
                status=status,
                available_at=available_at,
            )
        )
        await session.commit()
    return job


async def claim(session_factory: async_sessionmaker[AsyncSession]) -> DocumentProcessingJob | None:
    async with session_factory() as session:
        job = await DocumentProcessingJobRepository(session).claim_next(NOW)
        await session.commit()
    return job


async def claim_token(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    job = await claim(session_factory)
    assert job is not None and job.lease_token is not None
    return job.lease_token


async def reload(
    session_factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID
) -> DocumentProcessingJob:
    async with session_factory() as session:
        job = await DocumentProcessingJobRepository(session).get(job_id)
    assert job is not None
    return job


async def test_add_and_get(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(session_factory, source)

    saved = await reload(session_factory, job.id)

    assert (saved.document_id, saved.asset_id) == (job.document_id, job.asset_id)
    assert saved.status is ProcessingJobStatus.PENDING


async def test_get_returns_none_for_unknown_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        assert await DocumentProcessingJobRepository(session).get(uuid.uuid4()) is None


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
    assert saved.status is ProcessingJobStatus.RUNNING
    assert saved.claimed_at == NOW
    assert saved.attempt_count == 1
    assert saved.finished_at is None


async def test_job_available_right_now_is_claimed(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(session_factory, source, available_at=NOW)

    claimed = await claim(session_factory)

    assert claimed is not None
    assert claimed.id == job.id


async def test_future_job_is_skipped(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    await add_job(session_factory, source, available_at=NOW + timedelta(seconds=1))

    assert await claim(session_factory) is None


@pytest.mark.parametrize(
    "status",
    [ProcessingJobStatus.RUNNING, ProcessingJobStatus.COMPLETED, ProcessingJobStatus.FAILED],
)
async def test_jobs_that_are_not_pending_are_skipped(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    status: ProcessingJobStatus,
) -> None:
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
        assert await DocumentProcessingJobRepository(session).claim_next(NOW) is not None

    assert (await reload(session_factory, job.id)).status is ProcessingJobStatus.PENDING


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
        claimed_by_one = await DocumentProcessingJobRepository(one).claim_next(NOW)
        claimed_by_two = await DocumentProcessingJobRepository(two).claim_next(NOW)
        claimed_by_three = await DocumentProcessingJobRepository(three).claim_next(NOW)

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
        await DocumentProcessingJobRepository(session).mark_completed(job.id, token, finished_at)
        await session.commit()

    saved = await reload(session_factory, job.id)
    assert saved.status is ProcessingJobStatus.COMPLETED
    assert saved.finished_at == finished_at
    assert saved.last_error is None


async def test_mark_failed(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(session_factory, source)
    token = await claim_token(session_factory)

    async with session_factory() as session:
        await DocumentProcessingJobRepository(session).mark_failed(
            job.id, token, NOW, "  PDF is encrypted.  "
        )
        await session.commit()

    saved = await reload(session_factory, job.id)
    assert saved.status is ProcessingJobStatus.FAILED
    assert saved.finished_at == NOW
    assert saved.last_error == "PDF is encrypted."


async def test_long_errors_are_shortened(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    job = await add_job(session_factory, source)
    token = await claim_token(session_factory)

    async with session_factory() as session:
        failed = await DocumentProcessingJobRepository(session).mark_failed(
            job.id, token, NOW, "x" * 5000
        )
        await session.commit()

    assert failed.last_error is not None
    assert len(failed.last_error) == 1000


async def test_only_running_jobs_can_finish(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    token = uuid.uuid4()
    job = await add_job(session_factory, source)

    async with session_factory() as session:
        with pytest.raises(InvalidProcessingJobStatusChangeError, match="is pending"):
            await DocumentProcessingJobRepository(session).mark_completed(job.id, token, NOW)

    token = await claim_token(session_factory)
    async with session_factory() as session:
        await DocumentProcessingJobRepository(session).mark_completed(job.id, token, NOW)
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(InvalidProcessingJobStatusChangeError, match="is completed"):
            await DocumentProcessingJobRepository(session).mark_failed(
                job.id, token, NOW, "Too late."
            )


async def test_finishing_unknown_job_is_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError, match="Document processing job was not found."):
            await DocumentProcessingJobRepository(session).mark_completed(
                uuid.uuid4(), uuid.uuid4(), NOW
            )
