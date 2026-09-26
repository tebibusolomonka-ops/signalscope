import asyncio
import hashlib
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text
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
from signalscope.embeddings.provider import EmbeddingError, EmbeddingInputRole
from signalscope.embeddings.registry import EmbeddingProviderRegistry

pytestmark = pytest.mark.anyio

TEXT = "Climate and water policy for climate risks."
FAST_LEASE = LeasePolicy(timedelta(milliseconds=60))
TIMEOUT_SECONDS = 10
# Far enough ahead that every lease has run out.
LATER = timedelta(hours=1)


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
    *providers: FakeEmbeddingProvider,
    lease: LeasePolicy | None = None,
    batch_size: int = 32,
) -> EmbeddingWorker:
    return EmbeddingWorker(
        session_factory,
        registry_with(*providers),
        lease=lease or LeasePolicy(),
        batch_size=batch_size,
    )


async def create_chunks(
    session_factory: async_sessionmaker[AsyncSession], *texts: str
) -> list[DocumentChunk]:
    chunks = [
        TextChunk(
            position=index,
            text=text,
            start_char=0,
            end_char=len(text),
            text_hash=hashlib.sha256(text.encode()).hexdigest(),
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
        return await repository.list_by_document(document.id)


async def queue(
    session_factory: async_sessionmaker[AsyncSession],
    chunks: list[DocumentChunk],
    provider: FakeEmbeddingProvider,
) -> None:
    await EmbeddingQueueService(session_factory).queue_chunks(
        [chunk.id for chunk in chunks], provider.provider_name, provider.model_name
    )


async def add_jobs(
    session_factory: async_sessionmaker[AsyncSession], chunks: list[DocumentChunk]
) -> None:
    async with session_factory() as session:
        session.add_all(
            EmbeddingJob(chunk_id=chunk.id, provider="test", model="words-4") for chunk in chunks
        )
        await session.commit()


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


async def jobs(session_factory: async_sessionmaker[AsyncSession]) -> list[EmbeddingJob]:
    async with session_factory() as session:
        return list(await session.scalars(select(EmbeddingJob).order_by(EmbeddingJob.created_at)))


async def test_no_job(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    assert await worker(session_factory, provider).run_once() == EmbeddingWorkerResult()
    assert provider.calls == []


async def test_one_job(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    [chunk] = await create_chunks(session_factory, TEXT)
    await queue(session_factory, [chunk], provider)

    result = await worker(session_factory, provider).run_once()

    assert (result.completed, result.failed, result.lease_lost) == (1, 0, 0)
    [job] = result.jobs
    assert job.status is EmbeddingJobStatus.COMPLETED
    assert provider.calls == [[TEXT]]
    # Stored chunks are passages. Only search queries use the query role.
    assert provider.roles == [EmbeddingInputRole.PASSAGE]
    [saved] = await embeddings(session_factory)
    assert saved.chunk_id == chunk.id
    assert (saved.provider, saved.model, saved.dimensions) == ("test", "words-4", 4)
    assert saved.chunk_text_hash == chunk.text_hash
    assert saved.embedding == [2.0, 0.0, 1.0, 1.0]


async def test_several_jobs_go_to_the_model_in_one_call(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunks = await create_chunks(session_factory, "Water.", "Energy.", "Climate.")
    await queue(session_factory, chunks, provider)

    result = await worker(session_factory, provider).run_once()

    assert result.completed == 3
    assert len(provider.calls) == 1
    assert sorted(provider.calls[0]) == ["Climate.", "Energy.", "Water."]
    stored = {item.chunk_id: item.embedding for item in await embeddings(session_factory)}
    assert stored == {
        chunks[0].id: [0.0, 0.0, 1.0, 1.0],
        chunks[1].id: [0.0, 1.0, 0.0, 1.0],
        chunks[2].id: [1.0, 0.0, 0.0, 1.0],
    }


async def test_batch_size_is_respected(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunks = await create_chunks(session_factory, *(f"Water {index}." for index in range(5)))
    await queue(session_factory, chunks, provider)
    embedding_worker = worker(session_factory, provider, batch_size=2)

    sizes = []
    while (result := await embedding_worker.run_once()).jobs:
        sizes.append(len(result.jobs))

    assert sizes == [2, 2, 1]
    assert [len(call) for call in provider.calls] == [2, 2, 1]


async def test_batch_size_must_be_positive(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    with pytest.raises(ValueError, match="batch_size"):
        worker(session_factory, provider, batch_size=0)


async def test_a_batch_holds_one_model(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    other = FakeEmbeddingProvider(model_name="energy-2", words=["energy"])
    chunks = await create_chunks(session_factory, "Water.", "Energy.")
    await queue(session_factory, chunks, provider)
    await queue(session_factory, chunks, other)
    embedding_worker = worker(session_factory, provider, other)

    first = await embedding_worker.run_once()
    second = await embedding_worker.run_once()

    assert {job.model for job in first.jobs} == {"energy-2"}
    assert {job.model for job in second.jobs} == {"words-4"}
    assert (len(other.calls), len(provider.calls)) == (1, 1)
    assert (await embedding_worker.run_once()).jobs == ()


async def test_jobs_for_models_without_a_provider_are_left_alone(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    [chunk] = await create_chunks(session_factory, TEXT)
    await EmbeddingQueueService(session_factory).queue_chunks([chunk.id], "test", "other-model")
    empty = EmbeddingWorker(session_factory, EmbeddingProviderRegistry())

    assert (await worker(session_factory, provider).run_once()).jobs == ()
    assert (await empty.run_once()).jobs == ()
    [job] = await jobs(session_factory)
    assert job.status is EmbeddingJobStatus.PENDING


async def test_current_embedding_is_kept_without_calling_the_model(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    [chunk] = await create_chunks(session_factory, TEXT)
    await add_jobs(session_factory, [chunk])
    await add_embedding(session_factory, chunk, provider, chunk.text_hash)

    result = await worker(session_factory, provider).run_once()

    assert result.completed == 1
    assert provider.calls == []
    [saved] = await embeddings(session_factory)
    assert saved.embedding == [9.0] * 4


async def test_only_chunks_that_need_it_go_to_the_model(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    current, missing = await create_chunks(session_factory, "Current.", "Missing.")
    await add_jobs(session_factory, [current, missing])
    await add_embedding(session_factory, current, provider, current.text_hash)

    result = await worker(session_factory, provider).run_once()

    assert result.completed == 2
    assert provider.calls == [["Missing."]]


async def test_stale_embedding_is_replaced(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    [chunk] = await create_chunks(session_factory, TEXT)
    await add_embedding(session_factory, chunk, provider, "0" * 64)
    await queue(session_factory, [chunk], provider)

    result = await worker(session_factory, provider).run_once()

    assert result.completed == 1
    [saved] = await embeddings(session_factory)
    assert saved.chunk_text_hash == chunk.text_hash
    assert saved.embedding == [2.0, 0.0, 1.0, 1.0]


async def test_wrong_vectors_fail_the_whole_batch(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunks = await create_chunks(session_factory, "Water.", "Energy.")
    await queue(session_factory, chunks, provider)
    provider.answer = [[1.0, 2.0], [1.0, 2.0]]

    result = await worker(session_factory, provider).run_once()

    assert (result.completed, result.failed) == (0, 2)
    for job in result.jobs:
        assert job.status is EmbeddingJobStatus.FAILED
        assert job.last_error is not None and "2 dimensions instead of 4" in job.last_error
    assert await embeddings(session_factory) == []


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (EmbeddingError("Model is not ready."), "Model is not ready."),
        (RuntimeError("Traceback with private details"), UNEXPECTED_EMBEDDING_ERROR),
    ],
    ids=["expected error", "unexpected error"],
)
async def test_model_error_fails_every_job_that_needed_it(
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeEmbeddingProvider,
    error: Exception,
    message: str,
) -> None:
    current, *missing = await create_chunks(session_factory, "Current.", "One.", "Two.")
    await add_jobs(session_factory, [current, *missing])
    await add_embedding(session_factory, current, provider, current.text_hash)
    provider.error = error

    result = await worker(session_factory, provider).run_once()

    assert (result.completed, result.failed) == (1, 2)
    by_chunk = {job.chunk_id: job for job in result.jobs}
    assert by_chunk[current.id].status is EmbeddingJobStatus.COMPLETED
    for chunk in missing:
        assert (by_chunk[chunk.id].status, by_chunk[chunk.id].last_error) == (
            EmbeddingJobStatus.FAILED,
            message,
        )


async def test_leases_are_extended_while_the_model_runs(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunks = await create_chunks(session_factory, "Water.", "Energy.")
    await queue(session_factory, chunks, provider)
    provider.gate = asyncio.Event()
    run = asyncio.create_task(worker(session_factory, provider, lease=FAST_LEASE).run_once())
    await asyncio.wait_for(provider.started.wait(), TIMEOUT_SECONDS)
    claimed = {job.id: job.heartbeat_at for job in await jobs(session_factory)}

    # Wait until every lease in the batch has been extended.
    async with asyncio.timeout(TIMEOUT_SECONDS):
        while any(job.heartbeat_at == claimed[job.id] for job in await jobs(session_factory)):
            await asyncio.sleep(0.01)
    provider.gate.set()
    result = await asyncio.wait_for(run, TIMEOUT_SECONDS)

    assert (result.completed, result.lease_lost) == (2, 0)


async def test_no_transaction_is_held_while_the_model_runs(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunks = await create_chunks(session_factory, "Water.", "Energy.")
    await queue(session_factory, chunks, provider)
    provider.gate = asyncio.Event()
    run = asyncio.create_task(worker(session_factory, provider).run_once())
    await asyncio.wait_for(provider.started.wait(), TIMEOUT_SECONDS)

    # NOWAIT fails at once if another transaction still locks the claimed rows.
    async with session_factory() as session:
        locked = list(await session.scalars(select(EmbeddingJob.id).with_for_update(nowait=True)))
        await session.rollback()
    provider.gate.set()
    result = await asyncio.wait_for(run, TIMEOUT_SECONDS)

    assert len(locked) == 2
    assert result.completed == 2


async def test_losing_every_lease_saves_nothing(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunks = await create_chunks(session_factory, "Water.", "Energy.")
    await queue(session_factory, chunks, provider)
    provider.gate = asyncio.Event()
    run = asyncio.create_task(worker(session_factory, provider, lease=FAST_LEASE).run_once())
    await asyncio.wait_for(provider.started.wait(), TIMEOUT_SECONDS)

    async with session_factory() as session:
        recovered = await EmbeddingJobRepository(session).recover_stale(utc_now() + LATER, 10)
        await session.commit()
    assert len(recovered) == 2
    # Keep the model busy until a heartbeat has seen that the jobs are gone.
    await asyncio.sleep(FAST_LEASE.duration.total_seconds() * 2)
    provider.gate.set()
    result = await asyncio.wait_for(run, TIMEOUT_SECONDS)

    assert (result.completed, result.lease_lost) == (0, 2)
    assert {job.status for job in await jobs(session_factory)} == {EmbeddingJobStatus.PENDING}
    assert await embeddings(session_factory) == []


async def test_one_job_taken_over_in_a_batch(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    kept, taken = await create_chunks(session_factory, "Water.", "Energy.")
    await queue(session_factory, [kept, taken], provider)
    provider.gate = asyncio.Event()
    # The default lease is long, so no heartbeat notices the takeover first.
    run = asyncio.create_task(worker(session_factory, provider).run_once())
    await asyncio.wait_for(provider.started.wait(), TIMEOUT_SECONDS)

    # Another worker takes over the second job after its lease ran out.
    async with session_factory() as session:
        [job] = await session.scalars(select(EmbeddingJob).where(EmbeddingJob.chunk_id == taken.id))
        job.lease_expires_at = utc_now() - timedelta(minutes=1)
        await session.commit()
    async with session_factory() as session:
        repository = EmbeddingJobRepository(session)
        [recovered] = await repository.recover_stale(utc_now(), 10)
        [other] = await repository.claim_batch(utc_now(), "test", "words-4", 10)
        await session.commit()
    assert recovered.chunk_id == other.chunk_id == taken.id
    provider.gate.set()
    result = await asyncio.wait_for(run, TIMEOUT_SECONDS)

    assert (result.completed, result.lease_lost) == (1, 1)
    saved = {job.chunk_id: job for job in await jobs(session_factory)}
    assert saved[kept.id].status is EmbeddingJobStatus.COMPLETED
    assert saved[taken.id].status is EmbeddingJobStatus.RUNNING
    assert saved[taken.id].lease_token == other.lease_token
    assert [item.chunk_id for item in await embeddings(session_factory)] == [kept.id]


async def test_deleted_chunk_is_left_alone(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    [chunk] = await create_chunks(session_factory, TEXT)
    await queue(session_factory, [chunk], provider)
    provider.gate = asyncio.Event()
    run = asyncio.create_task(worker(session_factory, provider).run_once())
    await asyncio.wait_for(provider.started.wait(), TIMEOUT_SECONDS)

    async with session_factory() as session:
        await session.execute(text("DELETE FROM document_chunks WHERE id = :id"), {"id": chunk.id})
        await session.commit()
    provider.gate.set()
    result = await asyncio.wait_for(run, TIMEOUT_SECONDS)

    assert (result.completed, result.lease_lost) == (0, 1)
    assert await embeddings(session_factory) == []


async def test_workers_running_at_the_same_time_share_the_jobs(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    chunks = await create_chunks(session_factory, *(f"Climate note {index}." for index in range(6)))
    await queue(session_factory, chunks, provider)

    results = await asyncio.gather(
        *(worker(session_factory, provider, batch_size=2).run_once() for _ in range(3))
    )

    claimed = [job.chunk_id for result in results for job in result.jobs]
    assert sorted(claimed) == sorted(chunk.id for chunk in chunks)
    assert len(await embeddings(session_factory)) == 6


async def test_heartbeat_drops_jobs_that_are_not_held(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    held = {uuid.uuid4(): uuid.uuid4()}

    assert await worker(session_factory, provider)._heartbeat(held) is False
    assert held == {}
