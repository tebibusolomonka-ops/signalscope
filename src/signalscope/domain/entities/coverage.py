import uuid
from dataclasses import dataclass

from sqlalchemy import and_, exists, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import NotFoundError
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.job import EntityExtractionJob, EntityExtractionJobStatus
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.queue import ACTIVE_STATUSES
from signalscope.domain.tenancy.scope import ContentScope


@dataclass(frozen=True, slots=True)
class EntityCoverage:
    chunk_count: int
    # Chunks whose extraction is current for their text, as the queue decides.
    extracted_count: int
    # Chunks with a pending or running job.
    pending_count: int
    # Chunks whose last job failed.
    failed_count: int


class EntityCoverageService:
    """Counts how many chunks one entity model has read. It never loads the model."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def for_document(
        self, document_id: uuid.UUID, provider: str, model: str
    ) -> EntityCoverage:
        async with self.session_factory() as session:
            if await session.get(Document, document_id) is None:
                raise NotFoundError("Document was not found.")
            return await _coverage(session, provider, model, document_id)

    async def overall(
        self, provider: str, model: str, scope: ContentScope | None = None
    ) -> EntityCoverage:
        """Count over every chunk in scope, or every chunk when there is no scope."""
        async with self.session_factory() as session:
            return await _coverage(session, provider, model, scope=scope)


async def _coverage(
    session: AsyncSession,
    provider: str,
    model: str,
    document_id: uuid.UUID | None = None,
    scope: ContentScope | None = None,
) -> EntityCoverage:
    mentions = select(EntityMention.id).where(
        EntityMention.chunk_id == DocumentChunk.id,
        EntityMention.provider == provider,
        EntityMention.model == model,
    )
    has_current = exists(mentions.where(EntityMention.chunk_text_hash == DocumentChunk.text_hash))
    has_stale = exists(mentions.where(EntityMention.chunk_text_hash != DocumentChunk.text_hash))
    status = EntityExtractionJob.status
    statement = (
        select(
            func.count(DocumentChunk.id),
            func.count(DocumentChunk.id).filter(
                and_(
                    or_(status == EntityExtractionJobStatus.COMPLETED, has_current),
                    not_(has_stale),
                    # A chunk that is queued again is not done yet.
                    or_(status.is_(None), status.not_in(ACTIVE_STATUSES)),
                )
            ),
            func.count(DocumentChunk.id).filter(status.in_(ACTIVE_STATUSES)),
            func.count(DocumentChunk.id).filter(status == EntityExtractionJobStatus.FAILED),
        )
        .select_from(DocumentChunk)
        .outerjoin(
            EntityExtractionJob,
            and_(
                EntityExtractionJob.chunk_id == DocumentChunk.id,
                EntityExtractionJob.provider == provider,
                EntityExtractionJob.model == model,
            ),
        )
    )
    if document_id is not None:
        statement = statement.where(DocumentChunk.document_id == document_id)
    if scope is not None:
        statement = statement.where(scope.document_condition(DocumentChunk.document_id))
    chunks, extracted, pending, failed = (await session.execute(statement)).one()
    return EntityCoverage(
        chunk_count=chunks, extracted_count=extracted, pending_count=pending, failed_count=failed
    )
