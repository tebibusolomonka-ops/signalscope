import uuid
from dataclasses import dataclass

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import NotFoundError
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.events.job import EventExtractionJob, EventExtractionJobStatus
from signalscope.domain.events.model import EventEvidence
from signalscope.domain.events.queue import ACTIVE_STATUSES


@dataclass(frozen=True, slots=True)
class EventCoverage:
    chunk_count: int
    # Chunks the model has read, as the queue decides: evidence or a completed job.
    extracted_count: int
    # Chunks with a pending or running job.
    pending_count: int
    # Chunks whose last job failed.
    failed_count: int


class EventCoverageService:
    """Counts how many chunks one event model has read. It never loads the model."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def for_document(
        self, document_id: uuid.UUID, provider: str, model: str
    ) -> EventCoverage:
        async with self.session_factory() as session:
            if await session.get(Document, document_id) is None:
                raise NotFoundError("Document was not found.")
            return await _coverage(session, provider, model, document_id)

    async def overall(self, provider: str, model: str) -> EventCoverage:
        async with self.session_factory() as session:
            return await _coverage(session, provider, model)


async def _coverage(
    session: AsyncSession, provider: str, model: str, document_id: uuid.UUID | None = None
) -> EventCoverage:
    has_evidence = exists(
        select(EventEvidence.id).where(
            EventEvidence.chunk_id == DocumentChunk.id,
            EventEvidence.provider == provider,
            EventEvidence.model == model,
        )
    )
    status = EventExtractionJob.status
    statement = (
        select(
            func.count(DocumentChunk.id),
            func.count(DocumentChunk.id).filter(
                and_(
                    or_(status == EventExtractionJobStatus.COMPLETED, has_evidence),
                    # A chunk that is queued again is not done yet.
                    or_(status.is_(None), status.not_in(ACTIVE_STATUSES)),
                )
            ),
            func.count(DocumentChunk.id).filter(status.in_(ACTIVE_STATUSES)),
            func.count(DocumentChunk.id).filter(status == EventExtractionJobStatus.FAILED),
        )
        .select_from(DocumentChunk)
        .outerjoin(
            EventExtractionJob,
            and_(
                EventExtractionJob.chunk_id == DocumentChunk.id,
                EventExtractionJob.provider == provider,
                EventExtractionJob.model == model,
            ),
        )
    )
    if document_id is not None:
        statement = statement.where(DocumentChunk.document_id == document_id)
    chunks, extracted, pending, failed = (await session.execute(statement)).one()
    return EventCoverage(
        chunk_count=chunks, extracted_count=extracted, pending_count=pending, failed_count=failed
    )
