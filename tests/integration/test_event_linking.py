import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.linking import EventLinkingResult, EventLinkingService
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

MARCH_4 = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)


async def create_event(
    session_factory: async_sessionmaker[AsyncSession],
    title: str = "River Flood in Porto",
    event_type: str = "flood",
    occurred_at: datetime | None = None,
) -> uuid.UUID:
    """An event reported by a chunk of a new document in a new source."""
    text = f"{title} {uuid.uuid4()}"
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
        [saved] = await repository.list_by_document(document.id)
        event = Event(event_type=event_type, title=title, occurred_at=occurred_at)
        session.add(event)
        await session.flush()
        session.add(EventEvidence(event_id=event.id, chunk_id=saved.id, provider="t", model="m"))
        await session.commit()
        return event.id


async def cluster_of(
    session_factory: async_sessionmaker[AsyncSession], event_id: uuid.UUID
) -> uuid.UUID | None:
    async with session_factory() as session:
        member = await session.get(EventClusterMember, event_id)
    return None if member is None else member.cluster_id


async def clusters(session_factory: async_sessionmaker[AsyncSession]) -> list[EventCluster]:
    async with session_factory() as session:
        return list(await session.scalars(select(EventCluster)))


@pytest.fixture
def service(session_factory: async_sessionmaker[AsyncSession]) -> EventLinkingService:
    return EventLinkingService(session_factory)


async def test_same_type_and_title_are_linked_across_documents(
    session_factory: async_sessionmaker[AsyncSession], service: EventLinkingService
) -> None:
    first = await create_event(session_factory)
    second = await create_event(session_factory, "  river  FLOOD in porto ")

    result = await service.link_unclustered()

    assert result == EventLinkingResult(events_checked=2, events_linked=2, clusters_created=1)
    assert await cluster_of(session_factory, first) == await cluster_of(session_factory, second)
    [cluster] = await clusters(session_factory)
    # The oldest event gives the title.
    assert (cluster.event_type, cluster.canonical_title, cluster.normalized_title) == (
        "flood",
        "River Flood in Porto",
        "river flood in porto",
    )


@pytest.mark.parametrize(
    ("other_title", "other_type"),
    [("River Flood in Lisbon", "flood"), ("River Flood in Porto", "storm")],
    ids=["different title", "different type"],
)
async def test_different_title_or_type_stay_apart(
    session_factory: async_sessionmaker[AsyncSession],
    service: EventLinkingService,
    other_title: str,
    other_type: str,
) -> None:
    first = await create_event(session_factory)
    second = await create_event(session_factory, other_title, other_type)

    result = await service.link_unclustered()

    assert result.clusters_created == 2
    assert await cluster_of(session_factory, first) != await cluster_of(session_factory, second)


async def test_same_title_on_another_day_stays_apart(
    session_factory: async_sessionmaker[AsyncSession], service: EventLinkingService
) -> None:
    first = await create_event(session_factory, occurred_at=MARCH_4)
    second = await create_event(session_factory, occurred_at=MARCH_4 + timedelta(days=1))

    await service.link_unclustered()

    assert await cluster_of(session_factory, first) != await cluster_of(session_factory, second)


async def test_same_utc_day_in_different_time_zones_is_linked(
    session_factory: async_sessionmaker[AsyncSession], service: EventLinkingService
) -> None:
    first = await create_event(session_factory, occurred_at=MARCH_4)
    # 23:00 on 4 March in UTC, written as 5 March in UTC+2.
    late = datetime(2026, 3, 5, 1, 0, tzinfo=timezone(timedelta(hours=2)))
    second = await create_event(session_factory, occurred_at=late)

    await service.link_unclustered()

    assert await cluster_of(session_factory, first) == await cluster_of(session_factory, second)


async def test_missing_dates_still_link_and_the_earliest_time_is_kept(
    session_factory: async_sessionmaker[AsyncSession], service: EventLinkingService
) -> None:
    undated = await create_event(session_factory)
    later = await create_event(session_factory, occurred_at=MARCH_4 + timedelta(hours=5))
    earlier = await create_event(session_factory, occurred_at=MARCH_4)

    await service.link_unclustered()

    cluster_ids = {await cluster_of(session_factory, event) for event in (undated, later, earlier)}
    assert len(cluster_ids) == 1
    [cluster] = await clusters(session_factory)
    assert cluster.occurred_at == MARCH_4


async def test_several_sources_share_one_cluster(
    session_factory: async_sessionmaker[AsyncSession], service: EventLinkingService
) -> None:
    events = [await create_event(session_factory) for _ in range(4)]

    await service.link_unclustered()

    assert len({await cluster_of(session_factory, event) for event in events}) == 1
    async with session_factory() as session:
        sources = await session.scalars(
            select(Document.source_id)
            .join(DocumentChunk, DocumentChunk.document_id == Document.id)
            .join(EventEvidence, EventEvidence.chunk_id == DocumentChunk.id)
            .where(EventEvidence.event_id.in_(events))
            .distinct()
        )
        assert len(list(sources)) == 4


async def test_linking_again_changes_nothing(
    session_factory: async_sessionmaker[AsyncSession], service: EventLinkingService
) -> None:
    event = await create_event(session_factory)
    first = await service.link_event(event)

    again = await service.link_event(event)

    assert first is not None and first.created_cluster is True
    assert again is not None and (again.cluster_id, again.created_cluster) == (
        first.cluster_id,
        False,
    )
    assert await service.link_unclustered() == EventLinkingResult()
    assert len(await clusters(session_factory)) == 1


async def test_unknown_event(service: EventLinkingService) -> None:
    assert await service.link_event(uuid.uuid4()) is None


async def test_limit(
    session_factory: async_sessionmaker[AsyncSession], service: EventLinkingService
) -> None:
    for _ in range(3):
        await create_event(session_factory)

    assert (await service.link_unclustered(limit=2)).events_checked == 2
    assert (await service.link_unclustered(limit=2)).events_checked == 1


async def test_concurrent_links_make_one_cluster(
    session_factory: async_sessionmaker[AsyncSession], service: EventLinkingService
) -> None:
    events = [await create_event(session_factory) for _ in range(4)]

    links = await asyncio.gather(*(service.link_event(event) for event in events * 2))

    assert all(link is not None for link in links)
    assert len({link.cluster_id for link in links if link is not None}) == 1
    assert len(await clusters(session_factory)) == 1
    async with session_factory() as session:
        members = list(await session.scalars(select(EventClusterMember)))
    assert len(members) == 4
