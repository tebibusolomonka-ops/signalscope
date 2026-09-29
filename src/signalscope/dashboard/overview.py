from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.claims.job import ClaimExtractionJob, ClaimExtractionJobStatus
from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.job import EntityExtractionJob, EntityExtractionJobStatus
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.job import EventExtractionJob, EventExtractionJobStatus
from signalscope.domain.events.model import Event
from signalscope.domain.events.repository import UNRESTRICTED, visible_events
from signalscope.domain.ingestion.model import IngestionJob, IngestionJobStatus
from signalscope.domain.investigations.model import Investigation
from signalscope.domain.processing.model import DocumentProcessingJob, ProcessingJobStatus
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.domain.sources.model import Source
from signalscope.domain.tenancy.scope import ContentScope


@dataclass(frozen=True, slots=True)
class DashboardOverview:
    sources: int
    documents: int
    chunks: int
    entities: int
    claims: int
    events: int
    event_clusters: int
    research_sessions: int
    investigations: int
    # Jobs waiting or running. Completed and failed jobs are not counted.
    pending_ingestion: int
    pending_processing: int
    pending_embeddings: int
    pending_entities: int
    pending_events: int
    pending_claims: int


class DashboardOverviewService:
    """Record counts and open queue work, in one SQL statement. Facts only, no scores.

    In a scope every count covers only that scope: entities and claims are
    counted when they have mentions or evidence in it, events and clusters
    when they have evidence in it, and jobs through their source, document
    or chunk. There is no count across organizations.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def overview(self, scope: ContentScope = UNRESTRICTED) -> DashboardOverview:
        values: list[Select[Any]] = [
            _count(Source, scope.owner_condition(Source.organization_id)),
            _count(Document, scope.source_condition(Document.source_id)),
            _count(DocumentChunk, scope.document_condition(DocumentChunk.document_id)),
            _entities(scope),
            _claims(scope),
            _count(Event, visible_events(scope, Event.id)),
            _count(
                EventCluster,
                exists().where(
                    EventClusterMember.cluster_id == EventCluster.id,
                    visible_events(scope, EventClusterMember.event_id),
                ),
            ),
            _count(ResearchSession, scope.owner_condition(ResearchSession.organization_id)),
            _count(Investigation, scope.owner_condition(Investigation.organization_id)),
            _pending(
                IngestionJob, IngestionJobStatus, scope.source_condition(IngestionJob.source_id)
            ),
            _pending(
                DocumentProcessingJob,
                ProcessingJobStatus,
                scope.document_condition(DocumentProcessingJob.document_id),
            ),
            _pending(
                EmbeddingJob, EmbeddingJobStatus, scope.chunk_condition(EmbeddingJob.chunk_id)
            ),
            _pending(
                EntityExtractionJob,
                EntityExtractionJobStatus,
                scope.chunk_condition(EntityExtractionJob.chunk_id),
            ),
            _pending(
                EventExtractionJob,
                EventExtractionJobStatus,
                scope.chunk_condition(EventExtractionJob.chunk_id),
            ),
            _pending(
                ClaimExtractionJob,
                ClaimExtractionJobStatus,
                scope.chunk_condition(ClaimExtractionJob.chunk_id),
            ),
        ]
        row = (
            await self.session.execute(select(*(value.scalar_subquery() for value in values)))
        ).one()
        return DashboardOverview(*row)


def _count(model: Any, condition: ColumnElement[bool]) -> Select[Any]:
    return select(func.count()).select_from(model).where(condition)


def _entities(scope: ContentScope) -> Select[Any]:
    if scope.is_unrestricted:
        return select(func.count()).select_from(Entity)
    return select(func.count(EntityMention.entity_id.distinct())).where(
        scope.document_condition(EntityMention.document_id)
    )


def _claims(scope: ContentScope) -> Select[Any]:
    if scope.is_unrestricted:
        return select(func.count()).select_from(Claim)
    return select(func.count(ClaimEvidence.claim_id.distinct())).where(
        scope.chunk_condition(ClaimEvidence.chunk_id)
    )


def _pending(model: Any, status: Any, condition: ColumnElement[bool]) -> Select[Any]:
    return (
        select(func.count())
        .select_from(model)
        .where(model.status.in_([status.PENDING, status.RUNNING]), condition)
    )
