import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import NotFoundError
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.search.embedding_queue import EmbeddingQueueResult, EmbeddingQueueService
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
PROVIDER = "test"
MODEL = "tiny-3"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def create_document(
    session_factory: async_sessionmaker[AsyncSession], *texts: str
) -> tuple[Document, list[DocumentChunk]]:
    chunks = [
        TextChunk(
            position=index,
            text=text,
            start_char=0,
            end_char=len(text),
            text_hash=text_hash(text),
        )
        for index, text in enumerate(texts)
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
        return document, await repository.list_by_document(document.id)


async def add_embedding(
    session_factory: async_sessionmaker[AsyncSession],
    chunk: DocumentChunk,
    chunk_text_hash: str | None = None,
    model: str = MODEL,
) -> None:
    async with session_factory() as session:
        session.add(
            ChunkEmbedding(
                chunk_id=chunk.id,
                provider=PROVIDER,
                model=model,
                dimensions=3,
                chunk_text_hash=chunk_text_hash or chunk.text_hash,
                embedding=[1.0, 0.0, 0.0],
            )
        )
        await session.commit()


async def add_job(
    session_factory: async_sessionmaker[AsyncSession],
    chunk: DocumentChunk,
    status: EmbeddingJobStatus,
) -> EmbeddingJob:
    async with session_factory() as session:
        job = EmbeddingJob(
            chunk_id=chunk.id,
            provider=PROVIDER,
            model=MODEL,
            status=status,
            available_at=NOW - timedelta(days=1),
            finished_at=NOW - timedelta(hours=1) if status is EmbeddingJobStatus.FAILED else None,
            attempt_count=1,
            last_error="Model timed out." if status is EmbeddingJobStatus.FAILED else None,
        )
        session.add(job)
        await session.commit()
    return job


async def jobs(session_factory: async_sessionmaker[AsyncSession]) -> list[EmbeddingJob]:
    async with session_factory() as session:
        return list(
            await session.scalars(
                select(EmbeddingJob).order_by(EmbeddingJob.provider, EmbeddingJob.model)
            )
        )


def service(session_factory: async_sessionmaker[AsyncSession]) -> EmbeddingQueueService:
    return EmbeddingQueueService(session_factory, clock=lambda: NOW)


async def test_document_without_chunks(session_factory: async_sessionmaker[AsyncSession]) -> None:
    document, _ = await create_document(session_factory)

    result = await service(session_factory).queue_document(document.id, PROVIDER, MODEL)

    assert result == EmbeddingQueueResult()
    assert await jobs(session_factory) == []


async def test_unknown_document(session_factory: async_sessionmaker[AsyncSession]) -> None:
    with pytest.raises(NotFoundError):
        await service(session_factory).queue_document(uuid.uuid4(), PROVIDER, MODEL)


async def test_new_chunks_get_jobs(session_factory: async_sessionmaker[AsyncSession]) -> None:
    document, chunks = await create_document(session_factory, "First.", "Second.", "Third.")

    result = await service(session_factory).queue_document(document.id, PROVIDER, MODEL)

    assert result == EmbeddingQueueResult(chunks_seen=3, jobs_created=3)
    saved = await jobs(session_factory)
    assert sorted(job.chunk_id for job in saved) == sorted(chunk.id for chunk in chunks)
    for job in saved:
        assert (job.provider, job.model) == (PROVIDER, MODEL)
        assert job.status is EmbeddingJobStatus.PENDING
        assert job.available_at == NOW


async def test_embedded_chunks_are_skipped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document, [embedded, missing] = await create_document(session_factory, "First.", "Second.")
    await add_embedding(session_factory, embedded)

    result = await service(session_factory).queue_document(document.id, PROVIDER, MODEL)

    assert result == EmbeddingQueueResult(chunks_seen=2, jobs_created=1, already_embedded=1)
    assert [job.chunk_id for job in await jobs(session_factory)] == [missing.id]


async def test_embedding_of_another_model_does_not_count(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document, [chunk] = await create_document(session_factory, "First.")
    await add_embedding(session_factory, chunk, model="other")

    result = await service(session_factory).queue_document(document.id, PROVIDER, MODEL)

    assert result == EmbeddingQueueResult(chunks_seen=1, jobs_created=1)


async def test_stale_embedding_is_queued_again(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document, [chunk] = await create_document(session_factory, "First.")
    await add_embedding(session_factory, chunk, chunk_text_hash=text_hash("Old text."))
    job = await add_job(session_factory, chunk, EmbeddingJobStatus.COMPLETED)

    result = await service(session_factory).queue_document(document.id, PROVIDER, MODEL)

    assert result == EmbeddingQueueResult(chunks_seen=1, jobs_created=1)
    [saved] = await jobs(session_factory)
    assert saved.id == job.id
    assert saved.status is EmbeddingJobStatus.PENDING
    assert saved.available_at == NOW


async def test_failed_job_is_queued_again(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document, [chunk] = await create_document(session_factory, "First.")
    job = await add_job(session_factory, chunk, EmbeddingJobStatus.FAILED)

    result = await service(session_factory).queue_document(document.id, PROVIDER, MODEL)

    assert result == EmbeddingQueueResult(chunks_seen=1, jobs_created=1)
    [saved] = await jobs(session_factory)
    assert saved.id == job.id
    assert saved.status is EmbeddingJobStatus.PENDING
    assert (saved.last_error, saved.finished_at) == (None, None)
    # The earlier attempts still count.
    assert saved.attempt_count == 1


@pytest.mark.parametrize("status", [EmbeddingJobStatus.PENDING, EmbeddingJobStatus.RUNNING])
async def test_active_job_is_not_duplicated(
    session_factory: async_sessionmaker[AsyncSession], status: EmbeddingJobStatus
) -> None:
    document, [chunk] = await create_document(session_factory, "First.")
    job = await add_job(session_factory, chunk, status)

    result = await service(session_factory).queue_document(document.id, PROVIDER, MODEL)

    assert result == EmbeddingQueueResult(chunks_seen=1, already_queued=1)
    [saved] = await jobs(session_factory)
    assert (saved.id, saved.status) == (job.id, status)


async def test_queueing_twice_adds_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document, _ = await create_document(session_factory, "First.", "Second.")
    await service(session_factory).queue_document(document.id, PROVIDER, MODEL)

    result = await service(session_factory).queue_document(document.id, PROVIDER, MODEL)

    assert result == EmbeddingQueueResult(chunks_seen=2, already_queued=2)
    assert len(await jobs(session_factory)) == 2


async def test_other_models_get_their_own_jobs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document, _ = await create_document(session_factory, "First.")
    await service(session_factory).queue_document(document.id, PROVIDER, MODEL)

    result = await service(session_factory).queue_document(document.id, PROVIDER, "tiny-4")

    assert result == EmbeddingQueueResult(chunks_seen=1, jobs_created=1)
    assert [job.model for job in await jobs(session_factory)] == [MODEL, "tiny-4"]


async def test_queue_chosen_chunks(session_factory: async_sessionmaker[AsyncSession]) -> None:
    _, [first, second, third] = await create_document(session_factory, "One.", "Two.", "Three.")
    await add_embedding(session_factory, second)

    result = await service(session_factory).queue_chunks(
        [first.id, second.id, first.id, uuid.uuid4()], PROVIDER, MODEL
    )

    # Repeated and unknown chunk IDs are ignored.
    assert result == EmbeddingQueueResult(chunks_seen=2, jobs_created=1, already_embedded=1)
    assert [job.chunk_id for job in await jobs(session_factory)] == [first.id]
    assert third.id not in {job.chunk_id for job in await jobs(session_factory)}


async def test_no_chunk_ids(session_factory: async_sessionmaker[AsyncSession]) -> None:
    assert await service(session_factory).queue_chunks([], PROVIDER, MODEL) == (
        EmbeddingQueueResult()
    )
