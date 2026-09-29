import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import SelectBase, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import InvalidInputError, NotFoundError
from signalscope.domain.claims.model import ClaimEvidence
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.events.cluster import EventClusterMember
from signalscope.domain.events.model import EventEvidence
from signalscope.domain.sources.model import Source
from signalscope.domain.sources.provenance import SourceProvenance, SourceProvenanceService
from signalscope.domain.tenancy.scope import ContentScope

MIN_COMPARED_SOURCES = 2
MAX_COMPARED_SOURCES = 10


@dataclass(frozen=True, slots=True)
class ComparedSource:
    source: Source
    provenance: SourceProvenance


@dataclass(frozen=True, slots=True)
class SourceComparison:
    """Observed facts about each source, side by side, and what they have in common.

    Sources come in the order they were asked for. Nothing is scored or ranked.
    """

    sources: tuple[ComparedSource, ...]
    # Event clusters that two or more of the sources report.
    shared_event_cluster_count: int
    # Entities (same normalized name and type) found in two or more of the sources.
    shared_entity_count: int
    # Claims (same normalized text and type) found in two or more of the sources.
    shared_claim_count: int


class SourceComparisonService:
    """Compares 2 to 10 sources with the same provenance counts, and shared counts.

    It describes what was observed. It does not say which source is better,
    more reliable or more trusted.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def compare(
        self, source_ids: Sequence[uuid.UUID], scope: ContentScope | None = None
    ) -> SourceComparison:
        """Compare sources that are all in scope. A source outside it is not found."""
        scope = scope or ContentScope.unrestricted()
        if len(set(source_ids)) != len(source_ids):
            raise InvalidInputError("Each source can only be compared once.")
        if not MIN_COMPARED_SOURCES <= len(source_ids) <= MAX_COMPARED_SOURCES:
            raise InvalidInputError(
                f"Compare from {MIN_COMPARED_SOURCES} to {MAX_COMPARED_SOURCES} sources."
            )
        found = {
            source.id: source
            for source in await self.session.scalars(
                select(Source).where(
                    Source.id.in_(source_ids), scope.owner_condition(Source.organization_id)
                )
            )
        }
        missing = [source_id for source_id in source_ids if source_id not in found]
        if missing:
            raise NotFoundError(f"Source was not found: {missing[0]}.")
        provenance = SourceProvenanceService(self.session)
        compared = []
        for source_id in source_ids:
            compared.append(
                ComparedSource(found[source_id], await provenance.profile(source_id, scope))
            )
        chunk_source = (
            select(DocumentChunk.id, Document.source_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.source_id.in_(source_ids))
            .subquery()
        )
        clusters = (
            select(EventClusterMember.cluster_id.label("item"), chunk_source.c.source_id)
            .join(EventEvidence, EventEvidence.event_id == EventClusterMember.event_id)
            .join(chunk_source, chunk_source.c.id == EventEvidence.chunk_id)
        )
        entities = (
            select(EntityMention.entity_id.label("item"), Document.source_id)
            .join(Document, Document.id == EntityMention.document_id)
            .where(Document.source_id.in_(source_ids))
        )
        claims = select(ClaimEvidence.claim_id.label("item"), chunk_source.c.source_id).join(
            chunk_source, chunk_source.c.id == ClaimEvidence.chunk_id
        )
        return SourceComparison(
            sources=tuple(compared),
            shared_event_cluster_count=await self._shared(clusters),
            shared_entity_count=await self._shared(entities),
            shared_claim_count=await self._shared(claims),
        )

    async def _shared(self, pairs: SelectBase) -> int:
        """How many items appear with two or more different sources in (item, source) rows."""
        rows = pairs.subquery()
        shared = (
            select(rows.c.item)
            .group_by(rows.c.item)
            .having(func.count(rows.c.source_id.distinct()) >= 2)
            .subquery()
        )
        return await self.session.scalar(select(func.count()).select_from(shared)) or 0
