import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import NotFoundError
from signalscope.domain.claims.job import ClaimExtractionJob, ClaimExtractionJobStatus
from signalscope.domain.claims.model import ClaimEvidence
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import ChunkKey, DocumentChunkRepository
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.scheduling import Clock, utc_now

ACTIVE_STATUSES = (ClaimExtractionJobStatus.PENDING, ClaimExtractionJobStatus.RUNNING)
# How many chunks one backlog transaction checks.
BACKLOG_PAGE_SIZE = 500


@dataclass(frozen=True, slots=True)
class ClaimQueueResult:
    chunks_seen: int = 0
    # New jobs plus failed jobs that were put back in the queue.
    jobs_created: int = 0
    # Chunks that already had a pending or running job.
    already_queued: int = 0
    # Chunks the model has already read.
    already_extracted: int = 0

    def __add__(self, other: "ClaimQueueResult") -> "ClaimQueueResult":
        return ClaimQueueResult(
            chunks_seen=self.chunks_seen + other.chunks_seen,
            jobs_created=self.jobs_created + other.jobs_created,
            already_queued=self.already_queued + other.already_queued,
            already_extracted=self.already_extracted + other.already_extracted,
        )


class ClaimExtractionQueue:
    """Queues claim extraction jobs for chunks in the caller's transaction.

    It never commits. A chunk is done for a model when it has claim evidence
    from that model or its job completed, since many chunks make no claim.
    Chunk text never changes: processing a document again makes new chunks,
    and the old ones take their evidence with them. So done chunks are never
    stale, and only failed jobs are put back in the queue.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def queue_chunks(
        self, chunk_ids: Collection[uuid.UUID], provider: str, model: str, now: datetime
    ) -> ClaimQueueResult:
        if not chunk_ids:
            return ClaimQueueResult()
        has_evidence = exists(
            select(ClaimEvidence.id).where(
                ClaimEvidence.chunk_id == DocumentChunk.id,
                ClaimEvidence.provider == provider,
                ClaimEvidence.model == model,
            )
        )
        rows = (
            await self.session.execute(
                select(DocumentChunk.id, ClaimExtractionJob.status, has_evidence)
                .outerjoin(
                    ClaimExtractionJob,
                    and_(
                        ClaimExtractionJob.chunk_id == DocumentChunk.id,
                        ClaimExtractionJob.provider == provider,
                        ClaimExtractionJob.model == model,
                    ),
                )
                .where(DocumentChunk.id.in_(set(chunk_ids)))
            )
        ).all()
        already_queued = already_extracted = 0
        new: list[uuid.UUID] = []
        failed: list[uuid.UUID] = []
        for chunk_id, status, evidence in rows:
            if status in ACTIVE_STATUSES:
                already_queued += 1
            elif evidence or status is ClaimExtractionJobStatus.COMPLETED:
                already_extracted += 1
            elif status is None:
                new.append(chunk_id)
            else:
                failed.append(chunk_id)
        created = await self._add(new, provider, model, now)
        requeued = await self._requeue(failed, provider, model, now)
        return ClaimQueueResult(
            chunks_seen=len(rows),
            jobs_created=created + requeued,
            # Another transaction may have queued some of these chunks meanwhile.
            already_queued=already_queued + len(new) - created + len(failed) - requeued,
            already_extracted=already_extracted,
        )

    async def _add(
        self, chunk_ids: list[uuid.UUID], provider: str, model: str, now: datetime
    ) -> int:
        if not chunk_ids:
            return 0
        result = await self.session.scalars(
            insert(ClaimExtractionJob)
            .values(
                [
                    {
                        "id": uuid.uuid4(),
                        "chunk_id": chunk_id,
                        "provider": provider,
                        "model": model,
                        "status": ClaimExtractionJobStatus.PENDING,
                        "available_at": now,
                    }
                    for chunk_id in chunk_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=["chunk_id", "provider", "model"])
            .returning(ClaimExtractionJob.id)
        )
        return len(result.all())

    async def _requeue(
        self, chunk_ids: list[uuid.UUID], provider: str, model: str, now: datetime
    ) -> int:
        if not chunk_ids:
            return 0
        result = await self.session.scalars(
            update(ClaimExtractionJob)
            .where(
                ClaimExtractionJob.chunk_id.in_(chunk_ids),
                ClaimExtractionJob.provider == provider,
                ClaimExtractionJob.model == model,
                ClaimExtractionJob.status == ClaimExtractionJobStatus.FAILED,
            )
            .values(
                status=ClaimExtractionJobStatus.PENDING,
                available_at=now,
                claimed_at=None,
                heartbeat_at=None,
                lease_expires_at=None,
                lease_token=None,
                finished_at=None,
                last_error=None,
            )
            .returning(ClaimExtractionJob.id)
            .execution_options(synchronize_session=False)
        )
        return len(result.all())


class ClaimExtractionQueueService:
    """Queues claim extraction jobs, in bounded transactions."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], clock: Clock = utc_now
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def queue_chunks(
        self, chunk_ids: Collection[uuid.UUID], provider: str, model: str
    ) -> ClaimQueueResult:
        async with self.session_factory() as session:
            try:
                result = await ClaimExtractionQueue(session).queue_chunks(
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
    ) -> ClaimQueueResult:
        """Queue jobs for existing chunks that model has not read.

        Chunks are checked page by page in a stable order, each page in its own
        transaction. At most limit jobs are created.
        """
        if limit is not None and limit < 1:
            raise ValueError("limit must be at least 1")
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        if document_id is not None:
            async with self.session_factory() as session:
                if await session.get(Document, document_id) is None:
                    raise NotFoundError("Document was not found.")
        total = ClaimQueueResult()
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
                    result = await ClaimExtractionQueue(session).queue_chunks(
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
