import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import NotFoundError
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import ChunkKey, DocumentChunkRepository
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.job import EntityExtractionJob, EntityExtractionJobStatus
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.sources.scheduling import Clock, utc_now

ACTIVE_STATUSES = (EntityExtractionJobStatus.PENDING, EntityExtractionJobStatus.RUNNING)
# How many chunks one backlog transaction checks.
BACKLOG_PAGE_SIZE = 500


@dataclass(frozen=True, slots=True)
class EntityQueueResult:
    chunks_seen: int = 0
    # New jobs plus finished jobs that were put back in the queue.
    jobs_created: int = 0
    # Chunks that already had a pending or running job.
    already_queued: int = 0
    # Chunks whose extraction is current for their text.
    already_extracted: int = 0

    def __add__(self, other: "EntityQueueResult") -> "EntityQueueResult":
        return EntityQueueResult(
            chunks_seen=self.chunks_seen + other.chunks_seen,
            jobs_created=self.jobs_created + other.jobs_created,
            already_queued=self.already_queued + other.already_queued,
            already_extracted=self.already_extracted + other.already_extracted,
        )


class EntityExtractionQueue:
    """Queues entity extraction jobs for chunks in the caller's transaction.

    It never commits. A chunk is current when its job completed, or it has
    mentions from the model, and no mention was made from other text. A chunk
    can have no entities at all, so a completed job alone is enough. A chunk
    has at most one job per provider and model, so a finished job is put back
    in the queue instead of adding a second one.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def queue_chunks(
        self, chunk_ids: Collection[uuid.UUID], provider: str, model: str, now: datetime
    ) -> EntityQueueResult:
        if not chunk_ids:
            return EntityQueueResult()
        mentions = select(EntityMention.id).where(
            EntityMention.chunk_id == DocumentChunk.id,
            EntityMention.provider == provider,
            EntityMention.model == model,
        )
        rows = (
            await self.session.execute(
                select(
                    DocumentChunk.id,
                    EntityExtractionJob.status,
                    exists(
                        mentions.where(EntityMention.chunk_text_hash == DocumentChunk.text_hash)
                    ),
                    exists(
                        mentions.where(EntityMention.chunk_text_hash != DocumentChunk.text_hash)
                    ),
                )
                .outerjoin(
                    EntityExtractionJob,
                    and_(
                        EntityExtractionJob.chunk_id == DocumentChunk.id,
                        EntityExtractionJob.provider == provider,
                        EntityExtractionJob.model == model,
                    ),
                )
                .where(DocumentChunk.id.in_(set(chunk_ids)))
            )
        ).all()
        already_queued = already_extracted = 0
        new: list[uuid.UUID] = []
        finished: list[uuid.UUID] = []
        for chunk_id, status, has_current, has_stale in rows:
            if status in ACTIVE_STATUSES:
                already_queued += 1
            elif not has_stale and (has_current or status is EntityExtractionJobStatus.COMPLETED):
                already_extracted += 1
            elif status is None:
                new.append(chunk_id)
            else:
                finished.append(chunk_id)
        created = await self._add(new, provider, model, now)
        requeued = await self._requeue(finished, provider, model, now)
        return EntityQueueResult(
            chunks_seen=len(rows),
            jobs_created=created + requeued,
            # Another transaction may have queued some of these chunks meanwhile.
            already_queued=already_queued + len(new) - created + len(finished) - requeued,
            already_extracted=already_extracted,
        )

    async def _add(
        self, chunk_ids: list[uuid.UUID], provider: str, model: str, now: datetime
    ) -> int:
        if not chunk_ids:
            return 0
        result = await self.session.scalars(
            insert(EntityExtractionJob)
            .values(
                [
                    {
                        "id": uuid.uuid4(),
                        "chunk_id": chunk_id,
                        "provider": provider,
                        "model": model,
                        "status": EntityExtractionJobStatus.PENDING,
                        "available_at": now,
                    }
                    for chunk_id in chunk_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=["chunk_id", "provider", "model"])
            .returning(EntityExtractionJob.id)
        )
        return len(result.all())

    async def _requeue(
        self, chunk_ids: list[uuid.UUID], provider: str, model: str, now: datetime
    ) -> int:
        if not chunk_ids:
            return 0
        result = await self.session.scalars(
            update(EntityExtractionJob)
            .where(
                EntityExtractionJob.chunk_id.in_(chunk_ids),
                EntityExtractionJob.provider == provider,
                EntityExtractionJob.model == model,
                EntityExtractionJob.status.not_in(ACTIVE_STATUSES),
            )
            .values(
                status=EntityExtractionJobStatus.PENDING,
                available_at=now,
                claimed_at=None,
                heartbeat_at=None,
                lease_expires_at=None,
                lease_token=None,
                finished_at=None,
                last_error=None,
            )
            .returning(EntityExtractionJob.id)
            .execution_options(synchronize_session=False)
        )
        return len(result.all())


class EntityExtractionQueueService:
    """Queues entity extraction jobs, in bounded transactions."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], clock: Clock = utc_now
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def queue_chunks(
        self, chunk_ids: Collection[uuid.UUID], provider: str, model: str
    ) -> EntityQueueResult:
        async with self.session_factory() as session:
            try:
                result = await EntityExtractionQueue(session).queue_chunks(
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
    ) -> EntityQueueResult:
        """Queue jobs for existing chunks that need extraction with model.

        Chunks are checked page by page in a stable order, each page in its own
        transaction. At most limit jobs are created, and chunks already done are
        skipped, so running this again moves on to the chunks that still need work.
        """
        if limit is not None and limit < 1:
            raise ValueError("limit must be at least 1")
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        if document_id is not None:
            async with self.session_factory() as session:
                if await session.get(Document, document_id) is None:
                    raise NotFoundError("Document was not found.")
        total = EntityQueueResult()
        after: ChunkKey | None = None
        while limit is None or total.jobs_created < limit:
            # A page never holds more chunks than jobs may still be created.
            size = page_size if limit is None else min(page_size, limit - total.jobs_created)
            async with self.session_factory() as session:
                try:
                    page = await DocumentChunkRepository(session).page(
                        after, size, document_id=document_id
                    )
                    if not page:
                        break
                    result = await EntityExtractionQueue(session).queue_chunks(
                        [chunk_id for chunk_id, _, _ in page], provider, model, self.clock()
                    )
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
            total += result
            _, last_document, last_position = page[-1]
            after = (last_document, last_position)
        return total
