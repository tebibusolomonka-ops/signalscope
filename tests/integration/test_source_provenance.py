import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from signalscope.core.errors import NotFoundError
from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.documents.revision import DocumentRevision
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.events.linking import EventLinkingService
from signalscope.domain.sources.provenance import SourceProvenance, SourceProvenanceService

pytestmark = pytest.mark.anyio

MARCH_4 = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)
HASH = "0" * 64


async def profile(
    session_factory: async_sessionmaker[AsyncSession], source_id: uuid.UUID
) -> SourceProvenance:
    async with session_factory() as session:
        return await SourceProvenanceService(session).profile(source_id)


async def chunks_of(
    session_factory: async_sessionmaker[AsyncSession], source_id: uuid.UUID
) -> list[DocumentChunk]:
    async with session_factory() as session:
        return list(
            await session.scalars(
                select(DocumentChunk)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(Document.source_id == source_id)
                .order_by(DocumentChunk.id)
            )
        )


async def add_mentions(
    session_factory: async_sessionmaker[AsyncSession], chunk: DocumentChunk, *names: str
) -> None:
    async with session_factory() as session:
        for name in names:
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
                    chunk_text_hash=HASH,
                )
            )
        await session.commit()


async def add_claim(
    session_factory: async_sessionmaker[AsyncSession], chunk: DocumentChunk, text: str
) -> None:
    async with session_factory() as session:
        claim = await session.scalar(select(Claim).where(Claim.normalized_text == text))
        if claim is None:
            claim = Claim(text=text, normalized_text=text, claim_type="statistic")
            session.add(claim)
            await session.flush()
        session.add(
            ClaimEvidence(
                claim_id=claim.id,
                chunk_id=chunk.id,
                surface_text=chunk.text[:4],
                start_char=0,
                end_char=4,
                provider="test",
                model="m",
            )
        )
        await session.commit()


async def test_unknown_source(session_factory: async_sessionmaker[AsyncSession]) -> None:
    with pytest.raises(NotFoundError):
        await profile(session_factory, uuid.uuid4())


async def test_empty_source(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory, "Quiet")

    assert await profile(session_factory, source) == SourceProvenance(
        source_id=source,
        document_count=0,
        first_document_at=None,
        last_document_at=None,
        first_published_at=None,
        last_published_at=None,
        entity_count=0,
        claim_count=0,
        event_count=0,
        event_cluster_count=0,
        cross_source_event_cluster_count=0,
        revision_count=0,
    )


async def test_documents_and_publication_range(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory, "Wire")
    async with session_factory() as session:
        session.add_all(
            [
                Document(source_id=source, published_at=MARCH_4),
                Document(source_id=source, published_at=datetime(2026, 5, 1, tzinfo=UTC)),
                Document(source_id=source),
            ]
        )
        await session.commit()
        stored = list(await session.scalars(select(Document.created_at)))

    found = await profile(session_factory, source)

    assert found.document_count == 3
    assert (found.first_published_at, found.last_published_at) == (
        MARCH_4,
        datetime(2026, 5, 1, tzinfo=UTC),
    )
    assert (found.first_document_at, found.last_document_at) == (min(stored), max(stored))


async def test_entities_claims_events_and_revisions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory, "Wire")
    other = await create_source(session_factory, "Paper")
    await report_event(session_factory, source, "Harbour flood", evidence_count=2)
    await report_event(session_factory, source, "Bridge closed", event_type="closure")
    await report_event(session_factory, other, "Market fire", event_type="fire")
    first, second, third = await chunks_of(session_factory, source)
    [other_chunk] = await chunks_of(session_factory, other)
    await add_mentions(session_factory, first, "porto", "lisbon")
    await add_mentions(session_factory, second, "porto")
    await add_mentions(session_factory, other_chunk, "madrid")
    await add_claim(session_factory, first, "prices rose")
    await add_claim(session_factory, third, "prices rose")
    await add_claim(session_factory, third, "wages fell")
    await add_claim(session_factory, other_chunk, "rent rose")
    async with session_factory() as session:
        session.add_all(
            DocumentRevision(document_id=first.document_id, version=version) for version in (1, 2)
        )
        await session.commit()

    found = await profile(session_factory, source)

    assert (found.entity_count, found.claim_count, found.event_count) == (2, 2, 2)
    assert found.revision_count == 2


async def test_event_clusters_and_cross_source_clusters(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    await report_event(session_factory, wire, "Harbour flood", occurred_at=MARCH_4)
    await report_event(session_factory, paper, "Harbour flood", occurred_at=MARCH_4)
    await report_event(session_factory, wire, "Bridge closed", event_type="closure")
    await report_event(session_factory, wire, "Bridge closed", event_type="closure")
    await report_event(session_factory, paper, "Market fire", event_type="fire")
    await EventLinkingService(session_factory).link_unclustered()

    wire_profile = await profile(session_factory, wire)
    paper_profile = await profile(session_factory, paper)

    assert (wire_profile.event_count, wire_profile.event_cluster_count) == (3, 2)
    # Only the flood is also reported by another source.
    assert wire_profile.cross_source_event_cluster_count == 1
    assert (paper_profile.event_cluster_count, paper_profile.cross_source_event_cluster_count) == (
        2,
        1,
    )
