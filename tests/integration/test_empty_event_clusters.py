import uuid
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from fake_events import FakeEventExtractor
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.asset_service import DocumentAssetService
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.documents.service import DocumentService
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.job import EventExtractionJob, EventExtractionJobStatus
from signalscope.domain.events.linking import EventLinkingService
from signalscope.domain.events.model import EventEvidence
from signalscope.domain.events.queue import EventExtractionQueueService
from signalscope.domain.events.repository import EventRepository
from signalscope.domain.events.worker import EventExtractionWorker
from signalscope.domain.processing.processor import DocumentProcessor
from signalscope.events.registry import EventExtractorRegistry
from signalscope.parsing.registry import create_default_parser_registry
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def blobs(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(tmp_path / "blobs")


async def clusters(session_factory: async_sessionmaker[AsyncSession]) -> set[uuid.UUID]:
    async with session_factory() as session:
        return set(await session.scalars(select(EventCluster.id)))


async def cluster_of(
    session_factory: async_sessionmaker[AsyncSession], event_id: uuid.UUID
) -> uuid.UUID:
    link = await EventLinkingService(session_factory).link_event(event_id)
    assert link is not None
    return link.cluster_id


async def chunk_of(
    session_factory: async_sessionmaker[AsyncSession], event_id: uuid.UUID
) -> DocumentChunk:
    async with session_factory() as session:
        chunk = await session.scalar(
            select(DocumentChunk)
            .join(EventEvidence, EventEvidence.chunk_id == DocumentChunk.id)
            .where(EventEvidence.event_id == event_id)
        )
    assert chunk is not None
    return chunk


async def test_only_empty_clusters_are_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory, "Wire")
    kept = await cluster_of(session_factory, await report_event(session_factory, source, "Flood"))
    async with session_factory() as session:
        empty = [
            EventCluster(event_type="fire", canonical_title=title, normalized_title=title.lower())
            for title in ("Fire A", "Fire B")
        ]
        session.add_all(empty)
        await session.commit()

    async with session_factory() as session:
        assert await EventRepository(session).delete_empty_clusters() == 2
        await session.commit()

    assert await clusters(session_factory) == {kept}


async def test_orphan_cleanup_deletes_the_emptied_cluster(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory, "Wire")
    lonely = await report_event(session_factory, source, "Bridge closed", event_type="closure")
    shared_first = await report_event(session_factory, source, "Flood")
    shared_second = await report_event(session_factory, source, "Flood")
    lonely_cluster = await cluster_of(session_factory, lonely)
    shared_cluster = await cluster_of(session_factory, shared_first)
    await cluster_of(session_factory, shared_second)
    for event_id in (lonely, shared_first):
        chunk = await chunk_of(session_factory, event_id)
        async with session_factory() as session:
            await session.execute(
                text("DELETE FROM document_chunks WHERE id = :id"), {"id": chunk.id}
            )
            await session.commit()

    async with session_factory() as session:
        assert await EventRepository(session).delete_orphaned_events() == 2
        await session.commit()

    remaining = await clusters(session_factory)
    assert lonely_cluster not in remaining
    assert shared_cluster in remaining


async def test_document_deletion_removes_its_empty_clusters(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory, "Wire")
    event = await report_event(session_factory, source, "Flood")
    other = await report_event(session_factory, source, "Fire", event_type="fire")
    await cluster_of(session_factory, event)
    kept = await cluster_of(session_factory, other)
    chunk = await chunk_of(session_factory, event)

    async with session_factory() as session:
        await DocumentService(session).delete(chunk.document_id)

    assert await clusters(session_factory) == {kept}


async def processed_document(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> DocumentAsset:
    async with session_factory() as session:
        source_id = await create_source(session_factory, f"Files {uuid.uuid4()}")
        document = Document(source_id=source_id, title="Report")
        session.add(document)
        await session.commit()
        asset = await DocumentAssetService(session, blobs).attach(
            document.id, filename="report.txt", content_type="text/plain", data=b"A flood hit."
        )
    await DocumentProcessor(session_factory, blobs, create_default_parser_registry()).process(
        asset.id
    )
    return asset


async def test_reprocessing_removes_emptied_clusters(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    asset = await processed_document(session_factory, blobs)
    async with session_factory() as session:
        [chunk_id] = await session.scalars(
            select(DocumentChunk.id).where(DocumentChunk.document_id == asset.document_id)
        )
    registry = EventExtractorRegistry()
    registry.register(FakeEventExtractor())
    await EventExtractionQueueService(session_factory).queue_chunks(
        [chunk_id], "test", "flood-words"
    )
    await EventExtractionWorker(session_factory, registry).run_once()
    assert len(await clusters(session_factory)) == 1

    await blobs.put(asset.storage_key, b"Nothing happened today.")
    await DocumentProcessor(session_factory, blobs, create_default_parser_registry()).process(
        asset.id
    )

    assert await clusters(session_factory) == set()


async def test_worker_rerun_leaves_no_empty_cluster(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    asset = await processed_document(session_factory, blobs)
    async with session_factory() as session:
        [chunk_id] = await session.scalars(
            select(DocumentChunk.id).where(DocumentChunk.document_id == asset.document_id)
        )
    registry = EventExtractorRegistry()
    registry.register(FakeEventExtractor())
    worker = EventExtractionWorker(session_factory, registry)
    await EventExtractionQueueService(session_factory).queue_chunks(
        [chunk_id], "test", "flood-words"
    )
    await worker.run_once()
    first = await clusters(session_factory)
    async with session_factory() as session:
        job = await session.scalar(select(EventExtractionJob))
        assert job is not None
        job.status = EventExtractionJobStatus.PENDING
        await session.commit()

    await worker.run_once()

    again = await clusters(session_factory)
    assert len(again) == 1
    assert again.isdisjoint(first)
    async with session_factory() as session:
        members = list(await session.scalars(select(EventClusterMember)))
    assert [member.cluster_id for member in members] == list(again)
