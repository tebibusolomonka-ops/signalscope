import asyncio
import hashlib
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_embeddings import FakeEmbeddingProvider
from signalscope.core.leases import LeasePolicy
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.domain.search.embedding_job_repository import EmbeddingJobRepository
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.search.embedding_queue import EmbeddingQueueService
from signalscope.domain.search.embedding_worker import (
    UNEXPECTED_EMBEDDING_ERROR,
    EmbeddingWorker,
    EmbeddingWorkerResult,
)
from signalscope.domain.sources.model import Source, SourceType
from signalscope.domain.sources.scheduling import utc_now
from signalscope.embeddings.provider import EmbeddingError
from signalscope.embeddings.registry import EmbeddingProviderRegistry

pytestmark = pytest.mark.anyio

TEXT = "Climate and water policy for climate risks."
FAST_LEASE = LeasePolicy(timedelta(milliseconds=60))
TIMEOUT_SECONDS = 10


@pytest.fixture
def provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


def registry_with(*providers: FakeEmbeddingProvider) -> EmbeddingProviderRegistry:
    registry = EmbeddingProviderRegistry()
    for provider in providers:
        registry.register(provider)
    return registry


def worker(
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeEmbeddingProvider,
    lease: LeasePolicy | None = None,
) -> EmbeddingWorker:
    if lease is None:
        return EmbeddingWorker(session_factory, registry_with(provider))
    return EmbeddingWorker(session_factory, registry_with(provider), lease=lease)


async def create_chunk(
    session_factory: async_sessionmaker[AsyncSession], text: str = TEXT
) -> DocumentChunk:
    chunk = TextChunk(
        position=0,
        text=text,
        start_char=0,
        end_char=len(text),
        text_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, content=text)
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, [chunk])
        await session.commit()
        [saved] = await repository.list_by_document(document.id)
    return saved


async def queue(
    session_factory: async_sessionmaker[AsyncSession],
    chunk: DocumentChunk,
    provider: FakeEmbeddingProvider,
) -> None:
    await EmbeddingQueueService(session_factory).queue_chunks(
        [chunk.id], provider.provider_name, provider.model_name
    )


async def add_embedding(
    session_factory: async_sessionmaker[AsyncSession],
    chunk: DocumentChunk,
    provider: FakeEmbeddingProvider,
    chunk_text_hash: str,
) -> None:
    async with session_factory() as session:
        session.add(
            ChunkEmbedding(
                chunk_id=chunk.id,
                provider=provider.provider_name,
                model=provider.model_name,
                dimensions=provider.dimensions,
                chunk_text_hash=chunk_text_hash,
                embedding=[9.0] * provider.dimensions,
            )
        )
        await session.commit()


async def embeddings(session_factory: async_sessionmaker[AsyncSession]) -> list[ChunkEmbedding]:
    async with session_factory() as session:
        return list(await session.scalars(select(ChunkEmbedding)))


async def only_job(session_factory: async_sessionmaker[AsyncSession]) -> EmbeddingJob:
    async with session_factory() as session:
        [job] = await session.scalars(select(EmbeddingJob))
    return job


async def test_no_job(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    assert await worker(session_factory, provider).run_once() == EmbeddingWorkerResult(job=None)
    assert provider.calls == []


async def test_chunk_is_embedded(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunk = await create_chunk(session_factory)
    await queue(session_factory, chunk, provider)

    result = await worker(session_factory, provider).run_once()

    assert result.job is not None
    assert result.job.status is EmbeddingJobStatus.COMPLETED
    assert result.lease_lost is False
    assert provider.calls == [[TEXT]]
    [saved] = await embeddings(session_factory)
    assert saved.chunk_id == chunk.id
    assert (saved.provider, saved.model, saved.dimensions) == ("test", "words-4", 4)
    assert saved.chunk_text_hash == chunk.text_hash
    assert saved.embedding == [2.0, 0.0, 1.0, 1.0]
    job = await only_job(session_factory)
    assert (job.status, job.attempt_count, job.lease_expires_at) == (
        EmbeddingJobStatus.COMPLETED,
        1,
        None,
    )


async def test_current_embedding_is_kept_without_calling_the_provider(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunk = await create_chunk(session_factory)
    async with session_factory() as session:
        session.add(EmbeddingJob(chunk_id=chunk.id, provider="test", model="words-4"))
        await session.commit()
    await add_embedding(session_factory, chunk, provider, chunk.text_hash)

    result = await worker(session_factory, provider).run_once()

    assert result.job is not None and result.job.status is EmbeddingJobStatus.COMPLETED
    assert provider.calls == []
    [saved] = await embeddings(session_factory)
    assert saved.embedding == [9.0] * 4


async def test_stale_embedding_is_replaced(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunk = await create_chunk(session_factory)
    await add_embedding(session_factory, chunk, provider, "0" * 64)
    await queue(session_factory, chunk, provider)

    result = await worker(session_factory, provider).run_once()

    assert result.job is not None and result.job.status is EmbeddingJobStatus.COMPLETED
    [saved] = await embeddings(session_factory)
    assert saved.chunk_text_hash == chunk.text_hash
    assert saved.embedding == [2.0, 0.0, 1.0, 1.0]


async def test_vector_with_wrong_dimensions_fails_the_job(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunk = await create_chunk(session_factory)
    await queue(session_factory, chunk, provider)
    provider.answer = [[1.0, 2.0]]

    result = await worker(session_factory, provider).run_once()

    assert result.job is not None and result.job.status is EmbeddingJobStatus.FAILED
    assert result.job.last_error is not None
    assert "2 dimensions instead of 4" in result.job.last_error
    assert await embeddings(session_factory) == []


async def test_jobs_for_models_without_a_provider_are_left_alone(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunk = await create_chunk(session_factory)
    await EmbeddingQueueService(session_factory).queue_chunks([chunk.id], "test", "other-model")

    assert (await worker(session_factory, provider).run_once()).job is None
    assert (await only_job(session_factory)).status is EmbeddingJobStatus.PENDING


async def test_empty_registry_claims_nothing(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunk = await create_chunk(session_factory)
    await queue(session_factory, chunk, provider)

    result = await EmbeddingWorker(session_factory, EmbeddingProviderRegistry()).run_once()

    assert result.job is None
    assert (await only_job(session_factory)).status is EmbeddingJobStatus.PENDING


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (EmbeddingError("Model is not ready."), "Model is not ready."),
        (RuntimeError("Traceback with private details"), UNEXPECTED_EMBEDDING_ERROR),
    ],
    ids=["expected error", "unexpected error"],
)
async def test_provider_error_fails_the_job(
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeEmbeddingProvider,
    error: Exception,
    message: str,
) -> None:
    chunk = await create_chunk(session_factory)
    await queue(session_factory, chunk, provider)
    provider.error = error

    result = await worker(session_factory, provider).run_once()

    assert result.job is not None
    assert (result.job.status, result.job.last_error) == (EmbeddingJobStatus.FAILED, message)
    assert await embeddings(session_factory) == []


async def test_lease_is_extended_while_the_model_runs(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunk = await create_chunk(session_factory)
    await queue(session_factory, chunk, provider)
    provider.gate = asyncio.Event()
    run = asyncio.create_task(worker(session_factory, provider, FAST_LEASE).run_once())
    await asyncio.wait_for(provider.started.wait(), TIMEOUT_SECONDS)
    claimed = await only_job(session_factory)

    # Wait until the lease has been extended past its first end at least twice.
    for _ in range(2):
        async with asyncio.timeout(TIMEOUT_SECONDS):
            while (await only_job(session_factory)).heartbeat_at == claimed.heartbeat_at:
                await asyncio.sleep(0.01)
        claimed = await only_job(session_factory)
    provider.gate.set()
    result = await asyncio.wait_for(run, TIMEOUT_SECONDS)

    assert result.lease_lost is False
    assert result.job is not None and result.job.status is EmbeddingJobStatus.COMPLETED
    assert len(await embeddings(session_factory)) == 1


# Far enough ahead that every lease has run out.
LATER = timedelta(hours=1)


async def recover(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        recovered = await EmbeddingJobRepository(session).recover_stale(utc_now() + LATER, limit=10)
        await session.commit()
    assert len(recovered) == 1


async def test_lost_lease_saves_nothing(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunk = await create_chunk(session_factory)
    await queue(session_factory, chunk, provider)
    provider.gate = asyncio.Event()
    run = asyncio.create_task(worker(session_factory, provider, FAST_LEASE).run_once())
    await asyncio.wait_for(provider.started.wait(), TIMEOUT_SECONDS)

    await recover(session_factory)
    # Keep the model busy until a heartbeat has seen that the job is gone.
    await asyncio.sleep(FAST_LEASE.duration.total_seconds())
    provider.gate.set()
    result = await asyncio.wait_for(run, TIMEOUT_SECONDS)

    assert result.lease_lost is True
    assert (await only_job(session_factory)).status is EmbeddingJobStatus.PENDING
    assert await embeddings(session_factory) == []


async def test_job_claimed_again_by_another_worker_is_left_alone(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunk = await create_chunk(session_factory)
    await queue(session_factory, chunk, provider)
    provider.gate = asyncio.Event()
    # The default lease is long, so no heartbeat runs before the model finishes.
    run = asyncio.create_task(worker(session_factory, provider).run_once())
    await asyncio.wait_for(provider.started.wait(), TIMEOUT_SECONDS)

    await recover(session_factory)
    async with session_factory() as session:
        # Recovery made the job available at its own time, so claim at that time too.
        other = await EmbeddingJobRepository(session).claim_next(
            utc_now() + LATER, [("test", "words-4")]
        )
        await session.commit()
    assert other is not None
    provider.gate.set()
    result = await asyncio.wait_for(run, TIMEOUT_SECONDS)

    assert result.lease_lost is True
    job = await only_job(session_factory)
    assert (job.status, job.attempt_count) == (EmbeddingJobStatus.RUNNING, 2)
    assert await embeddings(session_factory) == []


async def test_deleted_chunk_is_left_alone(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunk = await create_chunk(session_factory)
    await queue(session_factory, chunk, provider)
    provider.gate = asyncio.Event()
    run = asyncio.create_task(worker(session_factory, provider).run_once())
    await asyncio.wait_for(provider.started.wait(), TIMEOUT_SECONDS)

    async with session_factory() as session:
        await session.delete(await session.get(DocumentChunk, chunk.id))
        await session.commit()
    provider.gate.set()
    result = await asyncio.wait_for(run, TIMEOUT_SECONDS)

    assert result.lease_lost is True
    assert await embeddings(session_factory) == []


async def test_workers_running_at_the_same_time_share_the_jobs(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunks = [await create_chunk(session_factory, f"Climate note {index}.") for index in range(2)]
    for chunk in chunks:
        await queue(session_factory, chunk, provider)

    results = await asyncio.gather(
        *(worker(session_factory, provider).run_once() for _ in range(3))
    )

    claimed = [result.job.chunk_id for result in results if result.job is not None]
    assert sorted(claimed) == sorted(chunk.id for chunk in chunks)
    assert len(await embeddings(session_factory)) == 2


async def test_unknown_job_id_heartbeat(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    assert await worker(session_factory, provider)._heartbeat(uuid.uuid4()) is False
