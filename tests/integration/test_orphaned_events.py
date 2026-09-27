import uuid
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_events import FakeEventExtractor
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.asset_service import DocumentAssetService
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.documents.service import DocumentService
from signalscope.domain.events.job import EventExtractionJob, EventExtractionJobStatus
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.events.queue import EventExtractionQueueService
from signalscope.domain.events.repository import EventRepository
from signalscope.domain.events.worker import EventExtractionWorker
from signalscope.domain.processing.processor import DocumentProcessor
from signalscope.domain.sources.model import Source, SourceType
from signalscope.events.registry import EventExtractorRegistry
from signalscope.parsing.registry import create_default_parser_registry
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio

TEXT = b"The river flooded the town. Heavy rain fell."


@pytest.fixture
def blobs(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(tmp_path / "blobs")


async def create_document(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, data: bytes = TEXT
) -> DocumentAsset:
    """A processed text document with at least one chunk."""
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name=f"Files {uuid.uuid4()}")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, title="Report")
        session.add(document)
        await session.commit()
        asset = await DocumentAssetService(session, blobs).attach(
            document.id, filename="report.txt", content_type="text/plain", data=data
        )
    await process(session_factory, blobs, asset)
    return asset


async def process(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    asset: DocumentAsset,
    data: bytes | None = None,
) -> None:
    if data is not None:
        await blobs.put(asset.storage_key, data)
    processor = DocumentProcessor(session_factory, blobs, create_default_parser_registry())
    await processor.process(asset.id)


async def chunk_ids(
    session_factory: async_sessionmaker[AsyncSession], document_id: uuid.UUID
) -> list[uuid.UUID]:
    async with session_factory() as session:
        ids = await session.scalars(
            select(DocumentChunk.id)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.position)
        )
        return list(ids)


async def create_event(
    session_factory: async_sessionmaker[AsyncSession], *chunks: uuid.UUID
) -> uuid.UUID:
    """An event with one evidence row for each given chunk."""
    async with session_factory() as session:
        event = Event(event_type="flood", title="Town flooded")
        session.add(event)
        await session.flush()
        for chunk_id in chunks:
            session.add(
                EventEvidence(event_id=event.id, chunk_id=chunk_id, provider="test", model="m")
            )
        await session.commit()
        return event.id


async def event_ids(session_factory: async_sessionmaker[AsyncSession]) -> set[uuid.UUID]:
    async with session_factory() as session:
        return set(await session.scalars(select(Event.id)))


async def delete_chunk(
    session_factory: async_sessionmaker[AsyncSession], chunk_id: uuid.UUID
) -> None:
    async with session_factory() as session:
        await session.execute(text("DELETE FROM document_chunks WHERE id = :id"), {"id": chunk_id})
        await session.commit()


async def delete_orphans(
    session_factory: async_sessionmaker[AsyncSession],
    only: set[uuid.UUID] | None = None,
) -> int:
    async with session_factory() as session:
        deleted = await EventRepository(session).delete_orphaned_events(only)
        await session.commit()
        return deleted


async def test_event_whose_only_evidence_is_gone_is_deleted(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    asset = await create_document(session_factory, blobs)
    [chunk] = await chunk_ids(session_factory, asset.document_id)
    await create_event(session_factory, chunk)
    await delete_chunk(session_factory, chunk)

    assert await delete_orphans(session_factory) == 1
    assert await event_ids(session_factory) == set()


async def test_event_with_evidence_left_stays(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    first = await create_document(session_factory, blobs)
    second = await create_document(session_factory, blobs)
    [first_chunk] = await chunk_ids(session_factory, first.document_id)
    [second_chunk] = await chunk_ids(session_factory, second.document_id)
    event = await create_event(session_factory, first_chunk, second_chunk)

    await delete_chunk(session_factory, first_chunk)
    assert await delete_orphans(session_factory) == 0
    assert await event_ids(session_factory) == {event}

    await delete_chunk(session_factory, second_chunk)
    assert await delete_orphans(session_factory) == 1
    assert await event_ids(session_factory) == set()


async def test_only_the_given_events_are_checked(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    asset = await create_document(session_factory, blobs)
    [chunk] = await chunk_ids(session_factory, asset.document_id)
    kept = await create_event(session_factory, chunk)
    removed = await create_event(session_factory, chunk)
    await delete_chunk(session_factory, chunk)

    assert await delete_orphans(session_factory, set()) == 0
    assert await delete_orphans(session_factory, {removed}) == 1
    assert await event_ids(session_factory) == {kept}


async def test_reprocessing_a_document_removes_its_orphaned_events(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    asset = await create_document(session_factory, blobs)
    other = await create_document(session_factory, blobs, b"Another flood report.")
    [chunk] = await chunk_ids(session_factory, asset.document_id)
    [other_chunk] = await chunk_ids(session_factory, other.document_id)
    orphan = await create_event(session_factory, chunk)
    shared = await create_event(session_factory, chunk, other_chunk)

    await process(session_factory, blobs, asset, b"New text about a storm.")

    assert await event_ids(session_factory) == {shared}
    assert orphan not in await event_ids(session_factory)


async def test_deleting_a_document_removes_its_orphaned_events(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    asset = await create_document(session_factory, blobs)
    other = await create_document(session_factory, blobs, b"Another flood report.")
    [chunk] = await chunk_ids(session_factory, asset.document_id)
    [other_chunk] = await chunk_ids(session_factory, other.document_id)
    await create_event(session_factory, chunk)
    shared = await create_event(session_factory, chunk, other_chunk)

    async with session_factory() as session:
        await DocumentService(session, blobs).delete(asset.document_id)

    assert await event_ids(session_factory) == {shared}


async def test_worker_rerun_keeps_events_backed_elsewhere(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    asset = await create_document(session_factory, blobs)
    other = await create_document(session_factory, blobs, b"Another flood report.")
    [chunk] = await chunk_ids(session_factory, asset.document_id)
    [other_chunk] = await chunk_ids(session_factory, other.document_id)
    extractor = FakeEventExtractor(model_name="m")
    registry = EventExtractorRegistry()
    registry.register(extractor)
    worker = EventExtractionWorker(session_factory, registry)
    await EventExtractionQueueService(session_factory).queue_chunks([chunk], "test", "m")
    await worker.run_once()
    [first] = await event_ids(session_factory)
    # Another chunk now also backs the event the first run made.
    async with session_factory() as session:
        session.add(EventEvidence(event_id=first, chunk_id=other_chunk, provider="test", model="m"))
        job = await session.scalar(select(EventExtractionJob))
        assert job is not None
        job.status = EventExtractionJobStatus.PENDING
        await session.commit()

    await worker.run_once()

    events = await event_ids(session_factory)
    assert first in events
    assert len(events) == 2
    async with session_factory() as session:
        backing = await session.scalars(
            select(EventEvidence.chunk_id).where(EventEvidence.event_id == first)
        )
        assert list(backing) == [other_chunk]


async def test_worker_rerun_deletes_its_replaced_events(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    asset = await create_document(session_factory, blobs)
    [chunk] = await chunk_ids(session_factory, asset.document_id)
    extractor = FakeEventExtractor(model_name="m")
    registry = EventExtractorRegistry()
    registry.register(extractor)
    worker = EventExtractionWorker(session_factory, registry)
    await EventExtractionQueueService(session_factory).queue_chunks([chunk], "test", "m")
    await worker.run_once()
    first = await event_ids(session_factory)
    async with session_factory() as session:
        job = await session.scalar(select(EventExtractionJob))
        assert job is not None
        job.status = EventExtractionJobStatus.PENDING
        await session.commit()

    await worker.run_once()

    again = await event_ids(session_factory)
    assert len(again) == 1
    assert first.isdisjoint(again)
