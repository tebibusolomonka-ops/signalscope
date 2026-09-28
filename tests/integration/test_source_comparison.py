import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from signalscope.core.errors import InvalidInputError, NotFoundError
from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.events.linking import EventLinkingService
from signalscope.domain.sources.comparison import SourceComparison, SourceComparisonService

pytestmark = pytest.mark.anyio


async def compare(
    session_factory: async_sessionmaker[AsyncSession], *source_ids: uuid.UUID
) -> SourceComparison:
    async with session_factory() as session:
        return await SourceComparisonService(session).compare(list(source_ids))


async def first_chunk(
    session_factory: async_sessionmaker[AsyncSession], source_id: uuid.UUID
) -> DocumentChunk:
    async with session_factory() as session:
        chunk = await session.scalar(
            select(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.source_id == source_id)
            .limit(1)
        )
    assert chunk is not None
    return chunk


async def mention(
    session_factory: async_sessionmaker[AsyncSession], chunk: DocumentChunk, name: str
) -> None:
    async with session_factory() as session:
        entity = await session.scalar(select(Entity).where(Entity.normalized_name == name))
        if entity is None:
            entity = Entity(canonical_name=name, normalized_name=name, entity_type="city")
            session.add(entity)
            await session.flush()
        session.add(
            EntityMention(
                entity_id=entity.id,
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                surface_text=name,
                entity_type="city",
                start_char=0,
                end_char=len(name),
                provider="test",
                model="m",
                chunk_text_hash="0" * 64,
            )
        )
        await session.commit()


async def claim(
    session_factory: async_sessionmaker[AsyncSession], chunk: DocumentChunk, text: str
) -> None:
    async with session_factory() as session:
        found = await session.scalar(select(Claim).where(Claim.normalized_text == text))
        if found is None:
            found = Claim(text=text, normalized_text=text, claim_type="statistic")
            session.add(found)
            await session.flush()
        session.add(
            ClaimEvidence(
                claim_id=found.id,
                chunk_id=chunk.id,
                surface_text=chunk.text[:4],
                start_char=0,
                end_char=4,
                provider="test",
                model="m",
            )
        )
        await session.commit()


async def test_two_sources_side_by_side(session_factory: async_sessionmaker[AsyncSession]) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    await report_event(session_factory, wire, "Harbour flood")
    await report_event(session_factory, wire, "Bridge closed", event_type="closure")
    await report_event(session_factory, paper, "Market fire", event_type="fire")

    result = await compare(session_factory, paper, wire)

    # The order asked for is kept. It is not a ranking.
    assert [item.source.name for item in result.sources] == ["Paper", "Wire"]
    assert [item.provenance.event_count for item in result.sources] == [1, 2]
    assert [item.provenance.document_count for item in result.sources] == [1, 2]
    assert (
        result.shared_event_cluster_count,
        result.shared_entity_count,
        result.shared_claim_count,
    ) == (0, 0, 0)


async def test_shared_clusters_entities_and_claims(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    radio = await create_source(session_factory, "Radio")
    await report_event(session_factory, wire, "Harbour flood")
    await report_event(session_factory, paper, "Harbour flood")
    await report_event(session_factory, radio, "Harbour flood")
    await report_event(session_factory, radio, "Market fire", event_type="fire")
    await EventLinkingService(session_factory).link_unclustered()
    wire_chunk = await first_chunk(session_factory, wire)
    paper_chunk = await first_chunk(session_factory, paper)
    radio_chunk = await first_chunk(session_factory, radio)
    await mention(session_factory, wire_chunk, "porto")
    await mention(session_factory, paper_chunk, "porto")
    await mention(session_factory, radio_chunk, "lisbon")
    await claim(session_factory, wire_chunk, "prices rose")
    await claim(session_factory, radio_chunk, "prices rose")
    await claim(session_factory, paper_chunk, "wages fell")

    three = await compare(session_factory, wire, paper, radio)
    two = await compare(session_factory, paper, radio)

    assert len(three.sources) == 3
    assert (
        three.shared_event_cluster_count,
        three.shared_entity_count,
        three.shared_claim_count,
    ) == (1, 1, 1)
    assert (two.shared_event_cluster_count, two.shared_entity_count, two.shared_claim_count) == (
        1,
        0,
        0,
    )


async def test_unknown_source(session_factory: async_sessionmaker[AsyncSession]) -> None:
    wire = await create_source(session_factory, "Wire")
    missing = uuid.uuid4()

    with pytest.raises(NotFoundError, match=str(missing)):
        await compare(session_factory, wire, missing)


async def test_duplicate_sources_are_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")

    with pytest.raises(InvalidInputError, match="only be compared once"):
        await compare(session_factory, wire, paper, wire)


async def test_source_count_limits(session_factory: async_sessionmaker[AsyncSession]) -> None:
    sources = [await create_source(session_factory, f"Source {number}") for number in range(11)]

    with pytest.raises(InvalidInputError, match="from 2 to 10"):
        await compare(session_factory, sources[0])
    with pytest.raises(InvalidInputError, match="from 2 to 10"):
        await compare(session_factory, *sources)
    assert len((await compare(session_factory, *sources[:10])).sources) == 10
