import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_events import FakeEventExtractor
from signalscope.core.leases import LeasePolicy
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.events.job import EventExtractionJob, EventExtractionJobStatus
from signalscope.domain.events.job_repository import EventExtractionJobRepository
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.events.queue import EventExtractionQueueService
from signalscope.domain.events.worker import (
    UNEXPECTED_EXTRACTION_ERROR,
    EventExtractionWorker,
    EventWorkerResult,
)
from signalscope.domain.sources.model import Source, SourceType
from signalscope.domain.sources.scheduling import utc_now
from signalscope.events.provider import ExtractedEvent, InvalidExtractedEventError
from signalscope.events.registry import EventExtractorRegistry

pytestmark = pytest.mark.anyio

FAST_LEASE = LeasePolicy(timedelta(milliseconds=60))
TIMEOUT_SECONDS = 10
TEXT = "Heavy rain fell. The river flooded the town. A second flood hit the port."


@pytest.fixture
def extractor() -> FakeEventExtractor:
    return FakeEventExtractor()


def worker(
    session_factory: async_sessionmaker[AsyncSession],
    extractor: FakeEventExtractor,
    lease: LeasePolicy | None = None,
) -> EventExtractionWorker:
    registry = EventExtractorRegistry()
    registry.register(extractor)
    return EventExtractionWorker(session_factory, registry, lease=lease or LeasePolicy())


async def create_chunk(
    session_factory: async_sessionmaker[AsyncSession], value: str = TEXT
) -> DocumentChunk:
    chunk = TextChunk(
        position=0,
        text=value,
        start_char=0,
        end_char=len(value),
        text_hash=hashlib.sha256(value.encode()).hexdigest(),
        metadata={"page_number": 3},
    )
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id)
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, [chunk])
        await session.commit()
        [saved] = await repository.list_by_document(document.id)
    await EventExtractionQueueService(session_factory).queue_chunks(
        [saved.id], "test", "flood-words"
    )
    return saved


async def events(session_factory: async_sessionmaker[AsyncSession]) -> list[Event]:
    async with session_factory() as session:
        return list(await session.scalars(select(Event).order_by(Event.title)))


async def evidence(session_factory: async_sessionmaker[AsyncSession]) -> list[EventEvidence]:
    async with session_factory() as session:
        return list(await session.scalars(select(EventEvidence)))


async def only_job(session_factory: async_sessionmaker[AsyncSession]) -> EventExtractionJob:
    async with session_factory() as session:
        [job] = await session.scalars(select(EventExtractionJob))
    return job


async def test_no_job(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeEventExtractor
) -> None:
    assert await worker(session_factory, extractor).run_once() == EventWorkerResult(job=None)


async def test_one_event(session_factory: async_sessionmaker[AsyncSession]) -> None:
    extractor = FakeEventExtractor()
    when = datetime(2026, 9, 21, 6, 0, tzinfo=UTC)
    extractor.answer = [
        ExtractedEvent(
            event_type="Flood",
            title="Town flooded",
            summary="The river rose overnight.",
            occurred_at=when,
            confidence=0.9,
            metadata={"sentence": 1},
        )
    ]
    chunk = await create_chunk(session_factory)

    result = await worker(session_factory, extractor).run_once()

    assert result.job is not None and result.job.status is EventExtractionJobStatus.COMPLETED
    assert result.event_count == 1
    [event] = await events(session_factory)
    assert (event.event_type, event.title, event.summary, event.occurred_at) == (
        "flood",
        "Town flooded",
        "The river rose overnight.",
        when,
    )
    [row] = await evidence(session_factory)
    assert (row.event_id, row.chunk_id, row.confidence) == (event.id, chunk.id, 0.9)
    assert (row.provider, row.model, row.evidence_metadata) == (
        "test",
        "flood-words",
        {"sentence": 1},
    )


async def test_several_events(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeEventExtractor
) -> None:
    await create_chunk(session_factory)

    result = await worker(session_factory, extractor).run_once()

    assert result.event_count == 2
    assert [event.title for event in await events(session_factory)] == [
        "A second flood hit the port.",
        "The river flooded the town.",
    ]
    assert len(await evidence(session_factory)) == 2


async def test_no_events(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeEventExtractor
) -> None:
    await create_chunk(session_factory, "Schools stayed open.")

    result = await worker(session_factory, extractor).run_once()

    assert result.job is not None and result.job.status is EventExtractionJobStatus.COMPLETED
    assert (result.event_count, await events(session_factory)) == (0, [])


async def test_reading_again_replaces_the_events(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeEventExtractor
) -> None:
    await create_chunk(session_factory)
    await worker(session_factory, extractor).run_once()
    first = {event.id for event in await events(session_factory)}
    async with session_factory() as session:
        job = await session.scalar(select(EventExtractionJob))
        assert job is not None
        job.status = EventExtractionJobStatus.PENDING
        await session.commit()

    await worker(session_factory, extractor).run_once()

    again = await events(session_factory)
    assert len(again) == 2
    assert first.isdisjoint(event.id for event in again)
    assert len(await evidence(session_factory)) == 2


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (InvalidExtractedEventError("Model is not ready."), "Model is not ready."),
        (RuntimeError("Traceback with private details"), UNEXPECTED_EXTRACTION_ERROR),
    ],
    ids=["expected error", "unexpected error"],
)
async def test_model_error_fails_the_job_with_a_safe_message(
    session_factory: async_sessionmaker[AsyncSession],
    extractor: FakeEventExtractor,
    error: Exception,
    message: str,
) -> None:
    await create_chunk(session_factory)
    extractor.error = error

    result = await worker(session_factory, extractor).run_once()

    assert result.job is not None
    assert (result.job.status, result.job.last_error) == (EventExtractionJobStatus.FAILED, message)
    assert await events(session_factory) == []


async def test_lease_is_extended_and_no_transaction_is_held(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeEventExtractor
) -> None:
    await create_chunk(session_factory)
    extractor.gate = asyncio.Event()
    run = asyncio.create_task(worker(session_factory, extractor, FAST_LEASE).run_once())
    await asyncio.wait_for(extractor.started.wait(), TIMEOUT_SECONDS)
    claimed = await only_job(session_factory)

    # NOWAIT fails at once if another transaction still locks the claimed row.
    async with session_factory() as session:
        locked = list(
            await session.scalars(select(EventExtractionJob.id).with_for_update(nowait=True))
        )
        await session.rollback()
    async with asyncio.timeout(TIMEOUT_SECONDS):
        while (await only_job(session_factory)).heartbeat_at == claimed.heartbeat_at:
            await asyncio.sleep(0.01)
    extractor.gate.set()
    result = await asyncio.wait_for(run, TIMEOUT_SECONDS)

    assert len(locked) == 1
    assert result.job is not None and result.job.status is EventExtractionJobStatus.COMPLETED


async def test_job_taken_over_is_left_alone(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeEventExtractor
) -> None:
    await create_chunk(session_factory)
    extractor.gate = asyncio.Event()
    # The default lease is long, so no heartbeat notices the takeover first.
    run = asyncio.create_task(worker(session_factory, extractor).run_once())
    await asyncio.wait_for(extractor.started.wait(), TIMEOUT_SECONDS)

    later = utc_now() + timedelta(hours=1)
    async with session_factory() as session:
        repository = EventExtractionJobRepository(session)
        await repository.recover_stale(later, 10)
        other = await repository.claim_next(later, [("test", "flood-words")])
        await session.commit()
    assert other is not None
    extractor.gate.set()
    result = await asyncio.wait_for(run, TIMEOUT_SECONDS)

    assert result.lease_lost is True
    job = await only_job(session_factory)
    assert (job.status, job.lease_token) == (EventExtractionJobStatus.RUNNING, other.lease_token)
    assert await events(session_factory) == []


async def test_deleting_the_chunk_keeps_the_events(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeEventExtractor
) -> None:
    chunk = await create_chunk(session_factory)
    await worker(session_factory, extractor).run_once()

    async with session_factory() as session:
        await session.execute(text("DELETE FROM document_chunks WHERE id = :id"), {"id": chunk.id})
        await session.commit()

    assert await evidence(session_factory) == []
    assert len(await events(session_factory)) == 2
