import hashlib
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_events import FakeEventExtractor
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.job import EventExtractionJob, EventExtractionJobStatus
from signalscope.domain.events.linking import EventLink, EventLinkingService
from signalscope.domain.events.model import Event
from signalscope.domain.events.queue import EventExtractionQueueService
from signalscope.domain.events.worker import EventExtractionWorker
from signalscope.domain.sources.model import Source, SourceType
from signalscope.events.registry import EventExtractorRegistry

pytestmark = pytest.mark.anyio


async def queue_document(session_factory: async_sessionmaker[AsyncSession], text: str) -> None:
    """A new source and document with one chunk, queued for the fake model."""
    chunk = TextChunk(
        position=0,
        text=text,
        start_char=0,
        end_char=len(text),
        text_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name=f"Source {uuid.uuid4()}")
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


def worker(
    session_factory: async_sessionmaker[AsyncSession], linker: EventLinkingService | None = None
) -> EventExtractionWorker:
    registry = EventExtractorRegistry()
    registry.register(FakeEventExtractor())
    return EventExtractionWorker(session_factory, registry, linker=linker)


async def cluster_ids(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, uuid.UUID]:
    """The cluster of each event, by event title."""
    async with session_factory() as session:
        rows = await session.execute(
            select(Event.title, EventClusterMember.cluster_id).join(
                EventClusterMember, EventClusterMember.event_id == Event.id
            )
        )
        return {title: cluster_id for title, cluster_id in rows}


async def test_new_event_gets_a_cluster(session_factory: async_sessionmaker[AsyncSession]) -> None:
    await queue_document(session_factory, "The river flooded the town.")

    result = await worker(session_factory).run_once()

    assert (result.event_count, result.linked_count) == (1, 1)
    assert list(await cluster_ids(session_factory)) == ["The river flooded the town."]


async def test_same_event_in_two_documents_shares_a_cluster(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await queue_document(session_factory, "The river flooded the town.")
    await queue_document(session_factory, "The river flooded the town.")
    await queue_document(session_factory, "A flood hit the port.")

    for _ in range(3):
        await worker(session_factory).run_once()

    async with session_factory() as session:
        pairs = list(
            await session.execute(
                select(Event.title, EventClusterMember.cluster_id).join(
                    EventClusterMember, EventClusterMember.event_id == Event.id
                )
            )
        )
        clusters = list(await session.scalars(select(EventCluster)))
    assert len(pairs) == 3
    by_title: dict[str, set[uuid.UUID]] = {}
    for title, cluster_id in pairs:
        by_title.setdefault(title, set()).add(cluster_id)
    assert {title: len(ids) for title, ids in by_title.items()} == {
        "The river flooded the town.": 1,
        "A flood hit the port.": 1,
    }
    assert len(clusters) == 2


class BrokenLinker(EventLinkingService):
    async def link_event(self, event_id: uuid.UUID) -> EventLink | None:
        raise RuntimeError("linking broke")


async def test_linking_failure_keeps_the_extraction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await queue_document(session_factory, "The river flooded the town.")

    result = await worker(session_factory, BrokenLinker(session_factory)).run_once()

    assert result.job is not None
    assert result.job.status is EventExtractionJobStatus.COMPLETED
    assert (result.event_count, result.linked_count) == (1, 0)
    async with session_factory() as session:
        assert len(list(await session.scalars(select(Event)))) == 1
        [job] = await session.scalars(select(EventExtractionJob))
    assert job.status is EventExtractionJobStatus.COMPLETED
    assert await cluster_ids(session_factory) == {}
    # A later repair run links the event.
    assert (await EventLinkingService(session_factory).link_unclustered()).events_linked == 1


class CheckingLinker(EventLinkingService):
    """Checks that the job is already saved when linking starts."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(session_factory)
        self.statuses: list[EventExtractionJobStatus] = []

    async def link_event(self, event_id: uuid.UUID) -> EventLink | None:
        async with self.session_factory() as session:
            [job] = await session.scalars(select(EventExtractionJob))
            self.statuses.append(job.status)
        return await super().link_event(event_id)


async def test_linking_runs_after_the_job_is_committed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await queue_document(session_factory, "The river flooded the town.")
    linker = CheckingLinker(session_factory)

    await worker(session_factory, linker).run_once()

    assert linker.statuses == [EventExtractionJobStatus.COMPLETED]


async def test_failed_extraction_links_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await queue_document(session_factory, "The river flooded the town.")
    registry = EventExtractorRegistry()
    extractor = FakeEventExtractor()
    extractor.error = RuntimeError("model broke")
    registry.register(extractor)

    result = await EventExtractionWorker(session_factory, registry).run_once()

    assert result.linked_count == 0
    assert await cluster_ids(session_factory) == {}
