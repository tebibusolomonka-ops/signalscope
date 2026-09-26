import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import NotFoundError
from signalscope.core.leases import LeasePolicy
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.domain.search.embedding_job_repository import (
    EmbeddingJobRepository,
    InvalidEmbeddingJobStatusChangeError,
)
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
MODEL = ("test", "tiny-3")
OTHER_MODEL = ("test", "tiny-4")


async def create_chunk_ids(
    session_factory: async_sessionmaker[AsyncSession], count: int
) -> list[uuid.UUID]:
    chunks = [
        TextChunk(
            position=index,
            text=f"Chunk {index}.",
            start_char=0,
            end_char=8,
            text_hash=hashlib.sha256(f"Chunk {index}.".encode()).hexdigest(),
        )
        for index in range(count)
    ]
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id)
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunks)
        await session.commit()
        return [chunk.id for chunk in await repository.list_by_document(document.id)]


async def add_job(
    session_factory: async_sessionmaker[AsyncSession],
    chunk_id: uuid.UUID,
    model: tuple[str, str] = MODEL,
    available_at: datetime = NOW - timedelta(minutes=1),
    status: EmbeddingJobStatus = EmbeddingJobStatus.PENDING,
    lease_expires_at: datetime | None = None,
) -> EmbeddingJob:
    async with session_factory() as session:
        job = await EmbeddingJobRepository(session).add(
            EmbeddingJob(
                chunk_id=chunk_id,
                provider=model[0],
                model=model[1],
                available_at=available_at,
                status=status,
                lease_expires_at=lease_expires_at,
            )
        )
        await session.commit()
    return job


async def reload(
    session_factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID
) -> EmbeddingJob:
    async with session_factory() as session:
        job = await EmbeddingJobRepository(session).get(job_id)
    assert job is not None
    return job


async def claim(
    session_factory: async_sessionmaker[AsyncSession], models: list[tuple[str, str]] | None = None
) -> EmbeddingJob | None:
    async with session_factory() as session:
        job = await EmbeddingJobRepository(session).claim_next(
            NOW, [MODEL] if models is None else models
        )
        await session.commit()
    return job


async def claim_token(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    job = await claim(session_factory)
    assert job is not None and job.lease_token is not None
    return job.lease_token


async def test_claim_without_jobs_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert await claim(session_factory) is None


async def test_claim_marks_the_job_running_with_a_lease(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    [chunk_id] = await create_chunk_ids(session_factory, 1)
    job = await add_job(session_factory, chunk_id)

    claimed = await claim(session_factory)

    assert claimed is not None and claimed.id == job.id
    saved = await reload(session_factory, job.id)
    assert saved.status is EmbeddingJobStatus.RUNNING
    assert (saved.claimed_at, saved.heartbeat_at) == (NOW, NOW)
    assert saved.lease_expires_at == NOW + timedelta(minutes=5)
    assert saved.attempt_count == 1


async def test_claim_with_a_custom_lease(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    [chunk_id] = await create_chunk_ids(session_factory, 1)
    job = await add_job(session_factory, chunk_id)

    async with session_factory() as session:
        await EmbeddingJobRepository(session).claim_next(
            NOW, [MODEL], LeasePolicy(timedelta(seconds=30))
        )
        await session.commit()

    assert (await reload(session_factory, job.id)).lease_expires_at == NOW + timedelta(seconds=30)


async def test_only_jobs_for_the_given_models_are_claimed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first, second = await create_chunk_ids(session_factory, 2)
    other = await add_job(session_factory, first, OTHER_MODEL, NOW - timedelta(hours=1))
    mine = await add_job(session_factory, second, MODEL)

    claimed = await claim(session_factory)

    assert claimed is not None and claimed.id == mine.id
    assert await claim(session_factory) is None
    both = await claim(session_factory, [MODEL, OTHER_MODEL])
    assert both is not None and both.id == other.id


async def test_no_models_claims_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    [chunk_id] = await create_chunk_ids(session_factory, 1)
    await add_job(session_factory, chunk_id)

    assert await claim(session_factory, []) is None


async def test_future_and_finished_jobs_are_skipped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk_ids = await create_chunk_ids(session_factory, 4)
    await add_job(session_factory, chunk_ids[0], available_at=NOW + timedelta(seconds=1))
    for chunk_id, status in zip(
        chunk_ids[1:],
        [EmbeddingJobStatus.RUNNING, EmbeddingJobStatus.COMPLETED, EmbeddingJobStatus.FAILED],
        strict=True,
    ):
        await add_job(session_factory, chunk_id, status=status)

    assert await claim(session_factory) is None


async def test_job_available_longest_is_claimed_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first, second = await create_chunk_ids(session_factory, 2)
    await add_job(session_factory, first, available_at=NOW - timedelta(minutes=1))
    older = await add_job(session_factory, second, available_at=NOW - timedelta(minutes=10))

    claimed = await claim(session_factory)

    assert claimed is not None and claimed.id == older.id


async def test_locked_job_is_skipped(session_factory: async_sessionmaker[AsyncSession]) -> None:
    first_chunk, second_chunk = await create_chunk_ids(session_factory, 2)
    first = await add_job(session_factory, first_chunk, available_at=NOW - timedelta(minutes=2))
    second = await add_job(session_factory, second_chunk, available_at=NOW - timedelta(minutes=1))

    async with (
        session_factory() as one,
        session_factory() as two,
        session_factory() as three,
    ):
        # Nothing is committed, so every claim still holds its row lock.
        claimed_by_one = await EmbeddingJobRepository(one).claim_next(NOW, [MODEL])
        claimed_by_two = await EmbeddingJobRepository(two).claim_next(NOW, [MODEL])
        claimed_by_three = await EmbeddingJobRepository(three).claim_next(NOW, [MODEL])

    assert claimed_by_one is not None
    assert claimed_by_two is not None
    assert (claimed_by_one.id, claimed_by_two.id) == (first.id, second.id)
    assert claimed_by_three is None


async def test_workers_claiming_at_the_same_time_get_different_jobs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    jobs = [
        await add_job(session_factory, chunk_id)
        for chunk_id in await create_chunk_ids(session_factory, 3)
    ]

    claimed = await asyncio.gather(*(claim(session_factory) for _ in range(5)))

    claimed_ids = [job.id for job in claimed if job is not None]
    assert sorted(claimed_ids) == sorted(job.id for job in jobs)
    for job in jobs:
        assert (await reload(session_factory, job.id)).attempt_count == 1


async def test_heartbeat_extends_the_lease_of_a_running_job(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    [chunk_id] = await create_chunk_ids(session_factory, 1)
    job = await add_job(session_factory, chunk_id)
    token = await claim_token(session_factory)
    later = NOW + timedelta(minutes=2)

    async with session_factory() as session:
        held = await EmbeddingJobRepository(session).heartbeat(job.id, token, later)
        await session.commit()

    assert held is True
    saved = await reload(session_factory, job.id)
    assert saved.heartbeat_at == later
    assert saved.lease_expires_at == later + timedelta(minutes=5)


@pytest.mark.parametrize(
    "status", [EmbeddingJobStatus.PENDING, EmbeddingJobStatus.COMPLETED, EmbeddingJobStatus.FAILED]
)
async def test_heartbeat_of_a_job_that_is_not_running(
    session_factory: async_sessionmaker[AsyncSession], status: EmbeddingJobStatus
) -> None:
    token = uuid.uuid4()
    [chunk_id] = await create_chunk_ids(session_factory, 1)
    job = await add_job(session_factory, chunk_id, status=status)

    async with session_factory() as session:
        assert await EmbeddingJobRepository(session).heartbeat(job.id, token, NOW) is False
        assert (
            await EmbeddingJobRepository(session).heartbeat(uuid.uuid4(), uuid.uuid4(), NOW)
            is False
        )


async def test_stale_jobs_are_recovered(session_factory: async_sessionmaker[AsyncSession]) -> None:
    stale_chunk, live_chunk = await create_chunk_ids(session_factory, 2)
    stale = await add_job(
        session_factory, stale_chunk, status=EmbeddingJobStatus.RUNNING, lease_expires_at=NOW
    )
    live = await add_job(
        session_factory,
        live_chunk,
        status=EmbeddingJobStatus.RUNNING,
        lease_expires_at=NOW + timedelta(seconds=1),
    )

    async with session_factory() as session:
        recovered = await EmbeddingJobRepository(session).recover_stale(NOW, limit=10)
        await session.commit()

    assert [job.id for job in recovered] == [stale.id]
    saved = await reload(session_factory, stale.id)
    assert saved.status is EmbeddingJobStatus.PENDING
    assert saved.available_at == NOW
    assert (saved.claimed_at, saved.heartbeat_at, saved.lease_expires_at) == (None, None, None)
    assert (await reload(session_factory, live.id)).status is EmbeddingJobStatus.RUNNING
    claimed = await claim(session_factory)
    assert claimed is not None and claimed.id == stale.id


async def test_recovery_limit_must_be_positive(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(ValueError, match="at least 1"):
            await EmbeddingJobRepository(session).recover_stale(NOW, limit=0)


async def test_mark_completed(session_factory: async_sessionmaker[AsyncSession]) -> None:
    [chunk_id] = await create_chunk_ids(session_factory, 1)
    job = await add_job(session_factory, chunk_id)
    token = await claim_token(session_factory)
    finished_at = NOW + timedelta(minutes=3)

    async with session_factory() as session:
        await EmbeddingJobRepository(session).mark_completed(job.id, token, finished_at)
        await session.commit()

    saved = await reload(session_factory, job.id)
    assert saved.status is EmbeddingJobStatus.COMPLETED
    assert saved.finished_at == finished_at
    assert (saved.lease_expires_at, saved.last_error) == (None, None)


async def test_mark_failed(session_factory: async_sessionmaker[AsyncSession]) -> None:
    [chunk_id] = await create_chunk_ids(session_factory, 1)
    job = await add_job(session_factory, chunk_id)
    token = await claim_token(session_factory)

    async with session_factory() as session:
        await EmbeddingJobRepository(session).mark_failed(
            job.id, token, NOW, "  Model is not ready.  "
        )
        await session.commit()

    saved = await reload(session_factory, job.id)
    assert saved.status is EmbeddingJobStatus.FAILED
    assert saved.last_error == "Model is not ready."
    assert saved.finished_at == NOW
    assert saved.lease_expires_at is None


async def test_only_running_jobs_can_finish(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token = uuid.uuid4()
    [chunk_id] = await create_chunk_ids(session_factory, 1)
    job = await add_job(session_factory, chunk_id)

    async with session_factory() as session:
        with pytest.raises(InvalidEmbeddingJobStatusChangeError):
            await EmbeddingJobRepository(session).mark_completed(job.id, token, NOW)
        with pytest.raises(InvalidEmbeddingJobStatusChangeError):
            await EmbeddingJobRepository(session).mark_failed(job.id, token, NOW, "Too early.")


async def test_finishing_unknown_job_is_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError):
            await EmbeddingJobRepository(session).mark_completed(uuid.uuid4(), uuid.uuid4(), NOW)


async def test_claim_is_not_committed(session_factory: async_sessionmaker[AsyncSession]) -> None:
    [chunk_id] = await create_chunk_ids(session_factory, 1)
    job = await add_job(session_factory, chunk_id)

    async with session_factory() as session:
        assert await EmbeddingJobRepository(session).claim_next(NOW, [MODEL]) is not None

    assert (await reload(session_factory, job.id)).status is EmbeddingJobStatus.PENDING
