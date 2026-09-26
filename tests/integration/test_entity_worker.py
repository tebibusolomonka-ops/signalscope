import asyncio
import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_entities import FakeEntityExtractor
from signalscope.core.leases import LeasePolicy
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.job import EntityExtractionJob, EntityExtractionJobStatus
from signalscope.domain.entities.job_repository import EntityExtractionJobRepository
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.entities.queue import EntityExtractionQueueService
from signalscope.domain.entities.worker import (
    UNEXPECTED_EXTRACTION_ERROR,
    EntityExtractionWorker,
    EntityWorkerResult,
)
from signalscope.domain.sources.model import Source, SourceType
from signalscope.domain.sources.scheduling import utc_now
from signalscope.entities.provider import ExtractedEntityMention, InvalidEntityMentionError
from signalscope.entities.registry import EntityExtractorRegistry

pytestmark = pytest.mark.anyio

FAST_LEASE = LeasePolicy(timedelta(milliseconds=60))
TIMEOUT_SECONDS = 10


@pytest.fixture
def extractor() -> FakeEntityExtractor:
    return FakeEntityExtractor()


def worker(
    session_factory: async_sessionmaker[AsyncSession],
    extractor: FakeEntityExtractor,
    lease: LeasePolicy | None = None,
) -> EntityExtractionWorker:
    registry = EntityExtractorRegistry()
    registry.register(extractor)
    return EntityExtractionWorker(session_factory, registry, lease=lease or LeasePolicy())


async def create_chunks(
    session_factory: async_sessionmaker[AsyncSession], *texts: str
) -> list[DocumentChunk]:
    chunks = [
        TextChunk(
            position=index,
            text=value,
            start_char=0,
            end_char=len(value),
            text_hash=hashlib.sha256(value.encode()).hexdigest(),
            metadata={"page_number": index + 1},
        )
        for index, value in enumerate(texts)
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
        saved = await repository.list_by_document(document.id)
    await EntityExtractionQueueService(session_factory).queue_chunks(
        [chunk.id for chunk in saved], "test", "known-words"
    )
    return saved


async def mentions(session_factory: async_sessionmaker[AsyncSession]) -> list[EntityMention]:
    async with session_factory() as session:
        return list(
            await session.scalars(
                select(EntityMention).order_by(EntityMention.chunk_id, EntityMention.start_char)
            )
        )


async def entities(session_factory: async_sessionmaker[AsyncSession]) -> list[Entity]:
    async with session_factory() as session:
        return list(await session.scalars(select(Entity).order_by(Entity.normalized_name)))


async def only_job(session_factory: async_sessionmaker[AsyncSession]) -> EntityExtractionJob:
    async with session_factory() as session:
        [job] = await session.scalars(select(EntityExtractionJob))
    return job


async def test_no_job(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeEntityExtractor
) -> None:
    assert await worker(session_factory, extractor).run_once() == EntityWorkerResult(job=None)


async def test_one_entity(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeEntityExtractor
) -> None:
    [chunk] = await create_chunks(session_factory, "A speech by Merkel today.")

    result = await worker(session_factory, extractor).run_once()

    assert result.job is not None and result.job.status is EntityExtractionJobStatus.COMPLETED
    assert result.mention_count == 1
    [entity] = await entities(session_factory)
    assert (entity.canonical_name, entity.normalized_name, entity.entity_type) == (
        "Merkel",
        "merkel",
        "person",
    )
    [mention] = await mentions(session_factory)
    assert (mention.entity_id, mention.chunk_id, mention.document_id) == (
        entity.id,
        chunk.id,
        chunk.document_id,
    )
    assert chunk.text[mention.start_char : mention.end_char] == "Merkel"
    assert (mention.confidence, mention.provider, mention.model) == (0.75, "test", "known-words")
    assert mention.chunk_text_hash == chunk.text_hash


async def test_several_entities(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeEntityExtractor
) -> None:
    await create_chunks(session_factory, "Merkel met Macron in Berlin.")

    result = await worker(session_factory, extractor).run_once()

    assert result.mention_count == 3
    assert [
        (entity.canonical_name, entity.entity_type) for entity in await entities(session_factory)
    ] == [
        ("Berlin", "location"),
        ("Macron", "person"),
        ("Merkel", "person"),
    ]


async def test_the_same_entity_is_reused(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeEntityExtractor
) -> None:
    await create_chunks(session_factory, "Merkel spoke.", "Later Merkel left.")
    entity_worker = worker(session_factory, extractor)

    await entity_worker.run_once()
    await entity_worker.run_once()

    [entity] = await entities(session_factory)
    assert {mention.entity_id for mention in await mentions(session_factory)} == {entity.id}
    assert len(await mentions(session_factory)) == 2


async def test_another_type_is_another_entity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    extractor = FakeEntityExtractor()
    extractor.answer = [
        ExtractedEntityMention("Jordan", "person", 0, 6),
        ExtractedEntityMention("Jordan", "location", 17, 23),
    ]
    await create_chunks(session_factory, "Jordan flew from Jordan.")

    await worker(session_factory, extractor).run_once()

    # Both share the normalized name, so compare them without their order.
    assert {
        (entity.normalized_name, entity.entity_type) for entity in await entities(session_factory)
    } == {
        ("jordan", "location"),
        ("jordan", "person"),
    }


async def test_extracting_again_replaces_the_mentions(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeEntityExtractor
) -> None:
    [chunk] = await create_chunks(session_factory, "Merkel met Macron.")
    await worker(session_factory, extractor).run_once()
    first = {mention.id for mention in await mentions(session_factory)}
    async with session_factory() as session:
        # Put the finished job back in the queue, as a new extraction would.
        job = await session.scalar(select(EntityExtractionJob))
        assert job is not None
        job.status = EntityExtractionJobStatus.PENDING
        await session.commit()
    extractor.known = {"Macron": "person"}

    await worker(session_factory, extractor).run_once()

    again = await mentions(session_factory)
    assert [mention.surface_text for mention in again] == ["Macron"]
    assert first.isdisjoint(mention.id for mention in again)
    assert all(mention.chunk_id == chunk.id for mention in again)


async def test_invalid_output_fails_the_job(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeEntityExtractor
) -> None:
    await create_chunks(session_factory, "Merkel spoke.")
    extractor.answer = [ExtractedEntityMention("Merkel", "person", 1, 7)]

    result = await worker(session_factory, extractor).run_once()

    assert result.job is not None and result.job.status is EntityExtractionJobStatus.FAILED
    assert result.job.last_error is not None and "not at offsets 1:7" in result.job.last_error
    assert await mentions(session_factory) == []


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (InvalidEntityMentionError("Model is not ready."), "Model is not ready."),
        (RuntimeError("Traceback with private details"), UNEXPECTED_EXTRACTION_ERROR),
    ],
    ids=["expected error", "unexpected error"],
)
async def test_model_error_fails_the_job_with_a_safe_message(
    session_factory: async_sessionmaker[AsyncSession],
    extractor: FakeEntityExtractor,
    error: Exception,
    message: str,
) -> None:
    await create_chunks(session_factory, "Merkel spoke.")
    extractor.error = error

    result = await worker(session_factory, extractor).run_once()

    assert result.job is not None
    assert (result.job.status, result.job.last_error) == (EntityExtractionJobStatus.FAILED, message)


async def test_lease_is_extended_and_no_transaction_is_held(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeEntityExtractor
) -> None:
    await create_chunks(session_factory, "Merkel spoke.")
    extractor.gate = asyncio.Event()
    run = asyncio.create_task(worker(session_factory, extractor, FAST_LEASE).run_once())
    await asyncio.wait_for(extractor.started.wait(), TIMEOUT_SECONDS)
    claimed = await only_job(session_factory)

    # NOWAIT fails at once if another transaction still locks the claimed row.
    async with session_factory() as session:
        locked = list(
            await session.scalars(select(EntityExtractionJob.id).with_for_update(nowait=True))
        )
        await session.rollback()
    async with asyncio.timeout(TIMEOUT_SECONDS):
        while (await only_job(session_factory)).heartbeat_at == claimed.heartbeat_at:
            await asyncio.sleep(0.01)
    extractor.gate.set()
    result = await asyncio.wait_for(run, TIMEOUT_SECONDS)

    assert len(locked) == 1
    assert result.job is not None and result.job.status is EntityExtractionJobStatus.COMPLETED


async def test_job_taken_over_is_left_alone(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeEntityExtractor
) -> None:
    await create_chunks(session_factory, "Merkel spoke.")
    extractor.gate = asyncio.Event()
    # The default lease is long, so no heartbeat notices the takeover first.
    run = asyncio.create_task(worker(session_factory, extractor).run_once())
    await asyncio.wait_for(extractor.started.wait(), TIMEOUT_SECONDS)

    later = utc_now() + timedelta(hours=1)
    async with session_factory() as session:
        repository = EntityExtractionJobRepository(session)
        await repository.recover_stale(later, 10)
        other = await repository.claim_next(later, [("test", "known-words")])
        await session.commit()
    assert other is not None
    extractor.gate.set()
    result = await asyncio.wait_for(run, TIMEOUT_SECONDS)

    assert result.lease_lost is True
    job = await only_job(session_factory)
    assert (job.status, job.lease_token) == (EntityExtractionJobStatus.RUNNING, other.lease_token)
    assert await mentions(session_factory) == []


async def test_deleted_chunk_is_left_alone(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeEntityExtractor
) -> None:
    [chunk] = await create_chunks(session_factory, "Merkel spoke.")
    extractor.gate = asyncio.Event()
    run = asyncio.create_task(worker(session_factory, extractor).run_once())
    await asyncio.wait_for(extractor.started.wait(), TIMEOUT_SECONDS)

    async with session_factory() as session:
        await session.execute(text("DELETE FROM document_chunks WHERE id = :id"), {"id": chunk.id})
        await session.commit()
    extractor.gate.set()
    result = await asyncio.wait_for(run, TIMEOUT_SECONDS)

    assert result.lease_lost is True
    assert await mentions(session_factory) == []
