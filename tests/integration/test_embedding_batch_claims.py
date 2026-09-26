import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.domain.search.embedding_job_repository import EmbeddingJobRepository
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
PROVIDER = "test"
MODEL = "tiny-3"


async def create_chunk_ids(
    session_factory: async_sessionmaker[AsyncSession], count: int
) -> list[uuid.UUID]:
    chunks = [
        TextChunk(
            position=index,
            text=f"Chunk {index}.",
            start_char=0,
            end_char=9,
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


async def add_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    count: int,
    provider: str = PROVIDER,
    model: str = MODEL,
) -> list[EmbeddingJob]:
    chunk_ids = await create_chunk_ids(session_factory, count)
    async with session_factory() as session:
        jobs = [
            EmbeddingJob(
                chunk_id=chunk_id,
                provider=provider,
                model=model,
                # The first chunk has waited longest.
                available_at=NOW - timedelta(minutes=count - index),
            )
            for index, chunk_id in enumerate(chunk_ids)
        ]
        session.add_all(jobs)
        await session.commit()
    return jobs


async def claim(
    session_factory: async_sessionmaker[AsyncSession], limit: int = 10, model: str = MODEL
) -> list[EmbeddingJob]:
    async with session_factory() as session:
        jobs = await EmbeddingJobRepository(session).claim_batch(NOW, PROVIDER, model, limit)
        await session.commit()
    return jobs


async def test_nothing_to_claim(session_factory: async_sessionmaker[AsyncSession]) -> None:
    assert await claim(session_factory) == []


async def test_one_job(session_factory: async_sessionmaker[AsyncSession]) -> None:
    [job] = await add_jobs(session_factory, 1)

    [claimed] = await claim(session_factory)

    assert claimed.id == job.id
    assert claimed.status is EmbeddingJobStatus.RUNNING
    assert (claimed.claimed_at, claimed.heartbeat_at) == (NOW, NOW)
    assert claimed.lease_expires_at == NOW + timedelta(minutes=5)
    assert claimed.attempt_count == 1


async def test_several_jobs_oldest_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    jobs = await add_jobs(session_factory, 3)

    claimed = await claim(session_factory)

    assert [job.id for job in claimed] == [job.id for job in jobs]


async def test_limit(session_factory: async_sessionmaker[AsyncSession]) -> None:
    jobs = await add_jobs(session_factory, 5)

    first = await claim(session_factory, limit=2)
    rest = await claim(session_factory, limit=10)

    assert [job.id for job in first] == [job.id for job in jobs[:2]]
    assert [job.id for job in rest] == [job.id for job in jobs[2:]]


@pytest.mark.parametrize("limit", [0, 257])
async def test_limit_is_bounded(
    session_factory: async_sessionmaker[AsyncSession], limit: int
) -> None:
    with pytest.raises(ValueError, match="between 1 and 256"):
        await claim(session_factory, limit=limit)


async def test_other_providers_and_models_are_left_alone(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_jobs(session_factory, 1, provider="other")
    await add_jobs(session_factory, 1, model="tiny-4")
    [mine] = await add_jobs(session_factory, 1)

    assert [job.id for job in await claim(session_factory)] == [mine.id]
    assert len(await claim(session_factory, model="tiny-4")) == 1


async def test_future_and_running_jobs_are_left_alone(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    [future, running] = await add_jobs(session_factory, 2)
    async with session_factory() as session:
        saved_future = await session.get(EmbeddingJob, future.id)
        saved_running = await session.get(EmbeddingJob, running.id)
        assert saved_future is not None and saved_running is not None
        saved_future.available_at = NOW + timedelta(seconds=1)
        saved_running.status = EmbeddingJobStatus.RUNNING
        await session.commit()

    assert await claim(session_factory) == []


async def test_locked_jobs_are_skipped(session_factory: async_sessionmaker[AsyncSession]) -> None:
    jobs = await add_jobs(session_factory, 3)

    async with session_factory() as one, session_factory() as two:
        # Nothing is committed, so the first claim still holds its row locks.
        first = await EmbeddingJobRepository(one).claim_batch(NOW, PROVIDER, MODEL, 2)
        second = await EmbeddingJobRepository(two).claim_batch(NOW, PROVIDER, MODEL, 10)

    assert [job.id for job in first] == [job.id for job in jobs[:2]]
    assert [job.id for job in second] == [jobs[2].id]


async def test_batches_claimed_at_the_same_time_do_not_overlap(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    jobs = await add_jobs(session_factory, 12)

    batches = await asyncio.gather(*(claim(session_factory, limit=5) for _ in range(4)))

    claimed = [job.id for batch in batches for job in batch]
    assert sorted(claimed) == sorted(job.id for job in jobs)


async def test_every_job_gets_its_own_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_jobs(session_factory, 4)

    claimed = await claim(session_factory)

    tokens = [job.lease_token for job in claimed]
    assert None not in tokens
    assert len(set(tokens)) == 4
