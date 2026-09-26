"""Lease tokens of the three job queues.

Every claim gets a new token, and only the worker that has it may extend or
finish the job.
"""

import hashlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.leases import JobNotHeldError
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.ingestion.job_repository import IngestionJobRepository
from signalscope.domain.ingestion.model import IngestionJob, IngestionRun, IngestionStatus
from signalscope.domain.processing.job_repository import DocumentProcessingJobRepository
from signalscope.domain.processing.model import DocumentProcessingJob
from signalscope.domain.search.embedding_job import EmbeddingJob
from signalscope.domain.search.embedding_job_repository import EmbeddingJobRepository
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
MODEL = ("test", "tiny-3")

SessionFactory = async_sessionmaker[AsyncSession]


async def add_ingestion_job(session: AsyncSession) -> uuid.UUID:
    source = Source(type=SourceType.RSS, name="Feed", url="https://example.com/rss")
    session.add(source)
    await session.flush()
    run = IngestionRun(source_id=source.id, status=IngestionStatus.PENDING)
    session.add(run)
    await session.flush()
    job = IngestionJob(source_id=source.id, run_id=run.id, available_at=NOW)
    session.add(job)
    await session.flush()
    return job.id


async def add_processing_job(session: AsyncSession) -> uuid.UUID:
    source = Source(type=SourceType.UPLOAD, name="Files")
    session.add(source)
    await session.flush()
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
    job = DocumentProcessingJob(document_id=document.id, asset_id=asset.id, available_at=NOW)
    session.add(job)
    await session.flush()
    return job.id


async def add_embedding_job(session: AsyncSession) -> uuid.UUID:
    source = Source(type=SourceType.UPLOAD, name="Files")
    session.add(source)
    await session.flush()
    document = Document(source_id=source.id)
    session.add(document)
    await session.flush()
    text = "Chunk text."
    chunks = DocumentChunkRepository(session)
    await chunks.replace_for_document(
        document.id,
        [
            TextChunk(
                position=0,
                text=text,
                start_char=0,
                end_char=len(text),
                text_hash=hashlib.sha256(text.encode()).hexdigest(),
            )
        ],
    )
    [chunk] = await chunks.list_by_document(document.id)
    job = EmbeddingJob(chunk_id=chunk.id, provider=MODEL[0], model=MODEL[1], available_at=NOW)
    session.add(job)
    await session.flush()
    return job.id


@dataclass(frozen=True)
class Queue:
    name: str
    add: Callable[[AsyncSession], Awaitable[uuid.UUID]]
    repository: Callable[[AsyncSession], Any]
    claim: Callable[[Any, datetime], Awaitable[Any]]


async def claim_next(repository: Any, now: datetime) -> Any:
    return await repository.claim_next(now)


async def claim_embedding_job(repository: EmbeddingJobRepository, now: datetime) -> Any:
    # Embedding jobs are claimed in batches of one model.
    jobs = await repository.claim_batch(now, *MODEL, 1)
    return jobs[0] if jobs else None


QUEUES = [
    Queue("ingestion", add_ingestion_job, IngestionJobRepository, claim_next),
    Queue("processing", add_processing_job, DocumentProcessingJobRepository, claim_next),
    Queue("embedding", add_embedding_job, EmbeddingJobRepository, claim_embedding_job),
]


@pytest.fixture(params=QUEUES, ids=[queue.name for queue in QUEUES])
def queue(request: pytest.FixtureRequest) -> Queue:
    result: Queue = request.param
    return result


async def add(session_factory: SessionFactory, queue: Queue) -> uuid.UUID:
    async with session_factory() as session:
        job_id = await queue.add(session)
        await session.commit()
    return job_id


async def claim(session_factory: SessionFactory, queue: Queue, now: datetime = NOW) -> Any:
    async with session_factory() as session:
        job = await queue.claim(queue.repository(session), now)
        await session.commit()
    assert job is not None
    return job


async def reload(session_factory: SessionFactory, queue: Queue, job_id: uuid.UUID) -> Any:
    async with session_factory() as session:
        return await queue.repository(session).get(job_id)


async def recover(session_factory: SessionFactory, queue: Queue) -> None:
    async with session_factory() as session:
        recovered = await queue.repository(session).recover_stale(LATER, 10)
        await session.commit()
    assert len(recovered) == 1


async def heartbeat(
    session_factory: SessionFactory, queue: Queue, job_id: uuid.UUID, token: uuid.UUID
) -> bool:
    async with session_factory() as session:
        held: bool = await queue.repository(session).heartbeat(job_id, token, NOW)
        await session.commit()
    return held


async def test_new_job_has_no_token(session_factory: SessionFactory, queue: Queue) -> None:
    job_id = await add(session_factory, queue)

    assert (await reload(session_factory, queue, job_id)).lease_token is None


async def test_claim_creates_a_token(session_factory: SessionFactory, queue: Queue) -> None:
    job_id = await add(session_factory, queue)

    claimed = await claim(session_factory, queue)

    assert isinstance(claimed.lease_token, uuid.UUID)
    assert (await reload(session_factory, queue, job_id)).lease_token == claimed.lease_token


async def test_claiming_again_gives_a_new_token(
    session_factory: SessionFactory, queue: Queue
) -> None:
    await add(session_factory, queue)
    first = await claim(session_factory, queue)
    await recover(session_factory, queue)

    second = await claim(session_factory, queue, LATER)

    assert second.id == first.id
    assert second.lease_token not in (None, first.lease_token)


async def test_only_the_right_token_heartbeats(
    session_factory: SessionFactory, queue: Queue
) -> None:
    job_id = await add(session_factory, queue)
    claimed = await claim(session_factory, queue)

    assert await heartbeat(session_factory, queue, job_id, uuid.uuid4()) is False
    assert await heartbeat(session_factory, queue, job_id, claimed.lease_token) is True


async def test_recovery_clears_the_token(session_factory: SessionFactory, queue: Queue) -> None:
    job_id = await add(session_factory, queue)
    claimed = await claim(session_factory, queue)

    await recover(session_factory, queue)

    assert (await reload(session_factory, queue, job_id)).lease_token is None
    assert await heartbeat(session_factory, queue, job_id, claimed.lease_token) is False


@pytest.mark.parametrize("finish", ["completed", "failed"])
async def test_old_worker_cannot_finish_after_another_claim(
    session_factory: SessionFactory, queue: Queue, finish: str
) -> None:
    job_id = await add(session_factory, queue)
    old = await claim(session_factory, queue)
    await recover(session_factory, queue)
    new = await claim(session_factory, queue, LATER)

    async with session_factory() as session:
        repository = queue.repository(session)
        with pytest.raises(JobNotHeldError):
            if finish == "completed":
                await repository.mark_completed(job_id, old.lease_token, LATER)
            else:
                await repository.mark_failed(job_id, old.lease_token, LATER, "Too late.")

    saved = await reload(session_factory, queue, job_id)
    assert saved.status == "running"
    assert saved.lease_token == new.lease_token
    assert saved.last_error is None


async def test_finishing_clears_the_token(session_factory: SessionFactory, queue: Queue) -> None:
    job_id = await add(session_factory, queue)
    claimed = await claim(session_factory, queue)

    async with session_factory() as session:
        await queue.repository(session).mark_completed(job_id, claimed.lease_token, NOW)
        await session.commit()

    saved = await reload(session_factory, queue, job_id)
    assert (saved.status, saved.lease_token) == ("completed", None)
