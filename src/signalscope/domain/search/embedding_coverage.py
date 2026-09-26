import uuid
from dataclasses import dataclass

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import NotFoundError
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.domain.search.embedding_model import ChunkEmbedding


@dataclass(frozen=True, slots=True)
class EmbeddingCoverage:
    chunk_count: int
    # Chunks whose embedding matches their current text.
    embedded_count: int
    # Chunks with a pending or running job.
    pending_count: int
    # Chunks whose last job failed.
    failed_count: int


class EmbeddingCoverageService:
    """Counts how many chunks have an up to date embedding from one model."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def for_document(
        self, document_id: uuid.UUID, provider: str, model: str
    ) -> EmbeddingCoverage:
        async with self.session_factory() as session:
            if await session.get(Document, document_id) is None:
                raise NotFoundError("Document was not found.")
            return await _coverage(session, provider, model, document_id)

    async def overall(self, provider: str, model: str) -> EmbeddingCoverage:
        """Count over every chunk of every document."""
        async with self.session_factory() as session:
            return await _coverage(session, provider, model)


async def _coverage(
    session: AsyncSession, provider: str, model: str, document_id: uuid.UUID | None = None
) -> EmbeddingCoverage:
    # Each chunk has at most one embedding and one job per model, so the joins
    # never count a chunk twice.
    statement = (
        select(
            func.count(DocumentChunk.id),
            func.count(ChunkEmbedding.id).filter(
                ChunkEmbedding.chunk_text_hash == DocumentChunk.text_hash
            ),
            func.count(EmbeddingJob.id).filter(
                EmbeddingJob.status.in_([EmbeddingJobStatus.PENDING, EmbeddingJobStatus.RUNNING])
            ),
            func.count(EmbeddingJob.id).filter(EmbeddingJob.status == EmbeddingJobStatus.FAILED),
        )
        .select_from(DocumentChunk)
        .outerjoin(
            ChunkEmbedding,
            and_(
                ChunkEmbedding.chunk_id == DocumentChunk.id,
                ChunkEmbedding.provider == provider,
                ChunkEmbedding.model == model,
            ),
        )
        .outerjoin(
            EmbeddingJob,
            and_(
                EmbeddingJob.chunk_id == DocumentChunk.id,
                EmbeddingJob.provider == provider,
                EmbeddingJob.model == model,
            ),
        )
    )
    if document_id is not None:
        statement = statement.where(DocumentChunk.document_id == document_id)
    chunks, embedded, pending, failed = (await session.execute(statement)).one()
    return EmbeddingCoverage(
        chunk_count=chunks, embedded_count=embedded, pending_count=pending, failed_count=failed
    )
