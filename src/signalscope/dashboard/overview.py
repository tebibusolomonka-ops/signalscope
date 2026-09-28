from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.claims.job import ClaimExtractionJob, ClaimExtractionJobStatus
from signalscope.domain.claims.model import Claim
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.job import EntityExtractionJob, EntityExtractionJobStatus
from signalscope.domain.entities.model import Entity
from signalscope.domain.events.cluster import EventCluster
from signalscope.domain.events.job import EventExtractionJob, EventExtractionJobStatus
from signalscope.domain.events.model import Event
from signalscope.domain.ingestion.model import IngestionJob, IngestionJobStatus
from signalscope.domain.investigations.model import Investigation
from signalscope.domain.processing.model import DocumentProcessingJob, ProcessingJobStatus
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.domain.sources.model import Source


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
    """Record counts and open queue work, in one SQL statement. Facts only, no scores."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def overview(self) -> DashboardOverview:
        values: list[Select[Any]] = [
            *(
                select(func.count()).select_from(model)
                for model in (
                    Source,
                    Document,
                    DocumentChunk,
                    Entity,
                    Claim,
                    Event,
                    EventCluster,
                    ResearchSession,
                    Investigation,
                )
            ),
            _pending(IngestionJob, IngestionJobStatus),
            _pending(DocumentProcessingJob, ProcessingJobStatus),
            _pending(EmbeddingJob, EmbeddingJobStatus),
            _pending(EntityExtractionJob, EntityExtractionJobStatus),
            _pending(EventExtractionJob, EventExtractionJobStatus),
            _pending(ClaimExtractionJob, ClaimExtractionJobStatus),
        ]
        row = (
            await self.session.execute(select(*(value.scalar_subquery() for value in values)))
        ).one()
        return DashboardOverview(*row)


def _pending(model: Any, status: Any) -> Select[Any]:
    return (
        select(func.count())
        .select_from(model)
        .where(model.status.in_([status.PENDING, status.RUNNING]))
    )
