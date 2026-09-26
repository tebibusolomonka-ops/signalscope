import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, literal, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import NotFoundError
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.sources.scheduling import Clock, utc_now

ACTIVE_STATUSES = (EmbeddingJobStatus.PENDING, EmbeddingJobStatus.RUNNING)
# How many chunks one backlog transaction checks.
BACKLOG_PAGE_SIZE = 500


@dataclass(frozen=True, slots=True)
class EmbeddingTarget:
    """The provider and model that new chunks should be embedded with."""

    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class EmbeddingQueueResult:
    chunks_seen: int = 0
    # New jobs plus finished jobs that were put back in the queue.
    jobs_created: int = 0
    # Chunks that already had a pending or running job.
    already_queued: int = 0
    # Chunks whose embedding matches their current text.
    already_embedded: int = 0


class EmbeddingQueue:
    """Queues embedding jobs for chunks in the caller's transaction.

    It never commits. A chunk needs a job when it has no embedding for the
    provider and model, or when the embedding was made from other text. A chunk
    has at most one job per provider and model, so a finished job is put back
    in the queue instead of adding a second one.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def queue_document(
        self, document_id: uuid.UUID, provider: str, model: str, now: datetime
    ) -> EmbeddingQueueResult:
        chunk_ids = await self.session.scalars(
            select(DocumentChunk.id).where(DocumentChunk.document_id == document_id)
        )
        return await self.queue_chunks(list(chunk_ids), provider, model, now)

    async def queue_chunks(
        self, chunk_ids: Collection[uuid.UUID], provider: str, model: str, now: datetime
    ) -> EmbeddingQueueResult:
        if not chunk_ids:
            return EmbeddingQueueResult()
        rows = (
            await self.session.execute(
                select(
                    DocumentChunk.id,
                    DocumentChunk.text_hash,
                    ChunkEmbedding.chunk_text_hash,
                    EmbeddingJob.status,
                )
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
                .where(DocumentChunk.id.in_(set(chunk_ids)))
            )
        ).all()
        already_queued = already_embedded = 0
        new: list[uuid.UUID] = []
        finished: list[uuid.UUID] = []
        for chunk_id, text_hash, embedded_hash, status in rows:
            if embedded_hash == text_hash:
                already_embedded += 1
            elif status is None:
                new.append(chunk_id)
            elif status in ACTIVE_STATUSES:
                already_queued += 1
            else:
                finished.append(chunk_id)
        created = await self._add(new, provider, model, now)
        requeued = await self._requeue(finished, provider, model, now)
        return EmbeddingQueueResult(
            chunks_seen=len(rows),
            jobs_created=created + requeued,
            # Another transaction may have queued some of these chunks meanwhile.
            already_queued=already_queued + len(new) - created + len(finished) - requeued,
            already_embedded=already_embedded,
        )

    async def _add(
        self, chunk_ids: list[uuid.UUID], provider: str, model: str, now: datetime
    ) -> int:
        if not chunk_ids:
            return 0
        result = await self.session.scalars(
            insert(EmbeddingJob)
            .values(
                [
                    {
                        "id": uuid.uuid4(),
                        "chunk_id": chunk_id,
                        "provider": provider,
                        "model": model,
                        "status": EmbeddingJobStatus.PENDING,
                        "available_at": now,
                    }
                    for chunk_id in chunk_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=["chunk_id", "provider", "model"])
            .returning(EmbeddingJob.id)
        )
        return len(result.all())

    async def _requeue(
        self, chunk_ids: list[uuid.UUID], provider: str, model: str, now: datetime
    ) -> int:
        if not chunk_ids:
            return 0
        result = await self.session.scalars(
            update(EmbeddingJob)
            .where(
                EmbeddingJob.chunk_id.in_(chunk_ids),
                EmbeddingJob.provider == provider,
                EmbeddingJob.model == model,
                EmbeddingJob.status.not_in(ACTIVE_STATUSES),
            )
            .values(
                status=EmbeddingJobStatus.PENDING,
                available_at=now,
                claimed_at=None,
                heartbeat_at=None,
                lease_expires_at=None,
                lease_token=None,
                finished_at=None,
                last_error=None,
            )
            .returning(EmbeddingJob.id)
            .execution_options(synchronize_session=False)
        )
        return len(result.all())


class EmbeddingQueueService:
    """Queues embedding jobs, one transaction per call."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], clock: Clock = utc_now
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def queue_document(
        self, document_id: uuid.UUID, provider: str, model: str
    ) -> EmbeddingQueueResult:
        async with self.session_factory() as session:
            try:
                if await session.get(Document, document_id) is None:
                    raise NotFoundError("Document was not found.")
                result = await EmbeddingQueue(session).queue_document(
                    document_id, provider, model, self.clock()
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return result

    async def queue_chunks(
        self, chunk_ids: Collection[uuid.UUID], provider: str, model: str
    ) -> EmbeddingQueueResult:
        async with self.session_factory() as session:
            try:
                result = await EmbeddingQueue(session).queue_chunks(
                    chunk_ids, provider, model, self.clock()
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return result

    async def queue_backlog(
        self,
        provider: str,
        model: str,
        *,
        document_id: uuid.UUID | None = None,
        limit: int | None = None,
        page_size: int = BACKLOG_PAGE_SIZE,
    ) -> EmbeddingQueueResult:
        """Queue jobs for existing chunks that need an embedding from model.

        Chunks are checked page by page in a stable order, each page in its
        own transaction, so the whole table is never loaded at once. At most
        limit jobs are created. Chunks that are already done are skipped, so
        running this again moves on to the chunks that still need work.
        """
        if limit is not None and limit < 1:
            raise ValueError("limit must be at least 1")
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        if document_id is not None:
            async with self.session_factory() as session:
                if await session.get(Document, document_id) is None:
                    raise NotFoundError("Document was not found.")
        total = EmbeddingQueueResult()
        after: tuple[uuid.UUID, int] | None = None
        while limit is None or total.jobs_created < limit:
            # A page never holds more chunks than jobs may still be created.
            size = page_size if limit is None else min(page_size, limit - total.jobs_created)
            async with self.session_factory() as session:
                try:
                    page = await _chunk_page(session, document_id, after, size)
                    if not page:
                        break
                    result = await EmbeddingQueue(session).queue_chunks(
                        [chunk_id for chunk_id, _, _ in page], provider, model, self.clock()
                    )
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
            total = _add_results(total, result)
            _, last_document, last_position = page[-1]
            after = (last_document, last_position)
        return total


async def _chunk_page(
    session: AsyncSession,
    document_id: uuid.UUID | None,
    after: tuple[uuid.UUID, int] | None,
    size: int,
) -> list[tuple[uuid.UUID, uuid.UUID, int]]:
    """The next chunks in (document, position) order, after the given key."""
    statement = select(DocumentChunk.id, DocumentChunk.document_id, DocumentChunk.position)
    if document_id is not None:
        statement = statement.where(DocumentChunk.document_id == document_id)
    if after is not None:
        statement = statement.where(
            tuple_(DocumentChunk.document_id, DocumentChunk.position)
            > tuple_(literal(after[0]), literal(after[1]))
        )
    rows = await session.execute(
        statement.order_by(DocumentChunk.document_id, DocumentChunk.position).limit(size)
    )
    return [(chunk_id, document, position) for chunk_id, document, position in rows]


def _add_results(first: EmbeddingQueueResult, second: EmbeddingQueueResult) -> EmbeddingQueueResult:
    return EmbeddingQueueResult(
        chunks_seen=first.chunks_seen + second.chunks_seen,
        jobs_created=first.jobs_created + second.jobs_created,
        already_queued=first.already_queued + second.already_queued,
        already_embedded=first.already_embedded + second.already_embedded,
    )
