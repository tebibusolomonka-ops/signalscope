import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Exists, Select, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from signalscope.core.errors import NotFoundError
from signalscope.domain.claims.model import ClaimEvidence
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.documents.revision import DocumentRevision
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.events.cluster import EventClusterMember
from signalscope.domain.events.model import EventEvidence
from signalscope.domain.sources.model import Source
from signalscope.domain.tenancy.scope import ContentScope


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    """What SignalScope has observed about one source. Counts and dates only."""

    source_id: uuid.UUID
    document_count: int
    # When SignalScope first and last stored a document from the source.
    first_document_at: datetime | None
    last_document_at: datetime | None
    # The earliest and latest publication dates the documents give.
    first_published_at: datetime | None
    last_published_at: datetime | None
    # Distinct entities, claims and events found in its documents.
    entity_count: int
    claim_count: int
    event_count: int
    # Linked event clusters its events belong to.
    event_cluster_count: int
    # Those clusters that another source also reports.
    cross_source_event_cluster_count: int
    # Earlier versions kept when its documents changed.
    revision_count: int


class SourceProvenanceService:
    """Counts what has been observed about a source, with SQL aggregates.

    It gives facts, not a judgement: there is no credibility or trust score,
    and sources are not ranked against each other.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def profile(
        self, source_id: uuid.UUID, scope: ContentScope | None = None
    ) -> SourceProvenance:
        """The counts of one source.

        Only one count looks beyond the source: clusters other sources also
        report. In a scope, only other sources in that scope count there.
        """
        scope = scope or ContentScope.unrestricted()
        if await self.session.get(Source, source_id) is None:
            raise NotFoundError("Source was not found.")
        own = Document.source_id == source_id
        documents = select(Document.id).where(own)
        chunks = select(DocumentChunk.id).where(DocumentChunk.document_id.in_(documents))
        events = select(EventEvidence.event_id).where(EventEvidence.chunk_id.in_(chunks))
        clusters = func.count(EventClusterMember.cluster_id.distinct())
        # Each value is its own subquery, and all of them run in one statement.
        values: list[Select[Any]] = [
            select(func.count()).select_from(Document).where(own),
            select(func.min(Document.created_at)).where(own),
            select(func.max(Document.created_at)).where(own),
            select(func.min(Document.published_at)).where(own),
            select(func.max(Document.published_at)).where(own),
            select(func.count(EntityMention.entity_id.distinct())).where(
                EntityMention.document_id.in_(documents)
            ),
            select(func.count(ClaimEvidence.claim_id.distinct())).where(
                ClaimEvidence.chunk_id.in_(chunks)
            ),
            select(func.count(EventEvidence.event_id.distinct())).where(
                EventEvidence.chunk_id.in_(chunks)
            ),
            select(clusters).where(EventClusterMember.event_id.in_(events)),
            select(clusters).where(
                EventClusterMember.event_id.in_(events), _reported_elsewhere(source_id, scope)
            ),
            select(func.count())
            .select_from(DocumentRevision)
            .where(DocumentRevision.document_id.in_(documents)),
        ]
        row = (
            await self.session.execute(select(*(value.scalar_subquery() for value in values)))
        ).one()
        return SourceProvenance(source_id, *row)


def _reported_elsewhere(source_id: uuid.UUID, scope: ContentScope) -> Exists:
    """True when the cluster of the outer member row has evidence from another source in scope."""
    member = aliased(EventClusterMember)
    evidence = aliased(EventEvidence)
    chunk = aliased(DocumentChunk)
    document = aliased(Document)
    return exists().where(
        member.cluster_id == EventClusterMember.cluster_id,
        evidence.event_id == member.event_id,
        chunk.id == evidence.chunk_id,
        document.id == chunk.document_id,
        document.source_id != source_id,
        scope.source_condition(document.source_id),
    )
