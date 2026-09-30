import uuid
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.domain.claims.queue import ClaimExtractionQueue
from signalscope.domain.entities.queue import EntityExtractionQueue
from signalscope.domain.events.queue import EventExtractionQueue
from signalscope.domain.ingestion.model import (
    IngestionJob,
    IngestionJobStatus,
    IngestionRun,
    IngestionStatus,
)
from signalscope.domain.operations.access import operations_scope
from signalscope.domain.operations.failed_jobs import OperationsJob, job_from_row, job_select
from signalscope.domain.operations.queues import QUEUE_TABLES, OperationsQueue, QueueTable
from signalscope.domain.processing.model import DocumentProcessingJob, ProcessingJobStatus
from signalscope.domain.search.embedding_queue import EmbeddingQueue
from signalscope.domain.sources.model import Source
from signalscope.domain.sources.scheduling import SCHEDULABLE_TYPES, Clock, utc_now
from signalscope.domain.tenancy.policy import ContentAccessPolicy

JOB_NOT_FOUND = "Job was not found."
NOT_FAILED = "Only failed jobs can be retried."
ALREADY_CURRENT = "The chunk already has current results from this model, so nothing is retried."
ALREADY_QUEUED = "This work is already queued."
SOURCE_ACTIVE = "The source already has a queued or running ingestion."
NOT_FETCHED = "sources of this type cannot be ingested by a worker."


class ChunkQueue(Protocol):
    async def queue_chunks(self, chunk_ids: Any, provider: str, model: str, now: Any) -> Any: ...


CHUNK_QUEUES: dict[OperationsQueue, type[Any]] = {
    OperationsQueue.EMBEDDING: EmbeddingQueue,
    OperationsQueue.ENTITY_EXTRACTION: EntityExtractionQueue,
    OperationsQueue.EVENT_EXTRACTION: EventExtractionQueue,
    OperationsQueue.CLAIM_EXTRACTION: ClaimExtractionQueue,
}


class FailedJobRecoveryService:
    """Puts one failed job of an organization back in its queue.

    Each queue is retried the way that queue already requeues work:

    - Chunk jobs go through the queue's own queue_chunks, which skips chunks
      whose results are current for their text and clears the old lease.
    - A processing job becomes pending again; processing a file again
      replaces its earlier results, as worker recovery already does.
    - An ingestion run cannot leave the failed state, so the job gets a new
      pending run and the failed run stays as history.

    attempt_count is kept. The row is locked and checked in the same
    transaction as the change, so two retries cannot both succeed.
    """

    def __init__(
        self, session: AsyncSession, policy: ContentAccessPolicy, clock: Clock = utc_now
    ) -> None:
        self.session = session
        self.policy = policy
        self.clock = clock

    async def retry(
        self, organization_id: uuid.UUID, queue: OperationsQueue, job_id: uuid.UUID
    ) -> OperationsJob:
        scope = await operations_scope(self.policy, organization_id)
        table = QUEUE_TABLES[queue]
        try:
            job = await self.session.scalar(
                select(table.model)
                .where(table.model.id == job_id, table.in_scope(scope))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if job is None:
                raise NotFoundError(JOB_NOT_FOUND)
            if job.status != table.status("failed"):
                raise ConflictError(NOT_FAILED)
            if queue in CHUNK_QUEUES:
                await self._requeue_chunk_job(table, job)
            elif queue is OperationsQueue.PROCESSING:
                self._requeue_processing_job(job)
            else:
                await self._requeue_ingestion_job(job)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        row = (
            await self.session.execute(job_select(table, scope).where(table.model.id == job_id))
        ).one()
        return job_from_row(row)

    async def _requeue_chunk_job(self, table: QueueTable, job: Any) -> None:
        queue: ChunkQueue = CHUNK_QUEUES[table.queue](self.session)
        result = await queue.queue_chunks([job.chunk_id], job.provider, job.model, self.clock())
        if result.jobs_created == 1:
            return
        if result.already_queued:
            raise ConflictError(ALREADY_QUEUED)
        raise ConflictError(ALREADY_CURRENT)

    def _requeue_processing_job(self, job: DocumentProcessingJob) -> None:
        job.status = ProcessingJobStatus.PENDING
        _clear(job, self.clock())

    async def _requeue_ingestion_job(self, job: IngestionJob) -> None:
        source = await self.session.get(Source, job.source_id)
        if source is None:
            raise ConflictError("The source no longer exists.")
        if source.type not in SCHEDULABLE_TYPES:
            raise ConflictError(f"{source.type} {NOT_FETCHED}")
        active = await self.session.scalar(
            select(IngestionJob.id).where(
                IngestionJob.source_id == job.source_id,
                IngestionJob.status.in_([IngestionJobStatus.PENDING, IngestionJobStatus.RUNNING]),
            )
        )
        if active is not None:
            raise ConflictError(SOURCE_ACTIVE)
        run = IngestionRun(source_id=job.source_id, status=IngestionStatus.PENDING)
        self.session.add(run)
        await self.session.flush()
        job.run_id = run.id
        job.status = IngestionJobStatus.PENDING
        _clear(job, self.clock())


def _clear(job: Any, now: Any) -> None:
    """Make the job available now, without the lease or result of its last try."""
    job.available_at = now
    job.claimed_at = None
    job.heartbeat_at = None
    job.lease_expires_at = None
    job.lease_token = None
    job.finished_at = None
    job.last_error = None
