import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.domain.audit.service import AuditAction, SecurityAuditService
from signalscope.domain.ingestion.model import IngestionJob, IngestionRun, IngestionStatus
from signalscope.domain.ingestion.repository import IngestionRunRepository
from signalscope.domain.operations.access import operations_scope
from signalscope.domain.operations.queues import (
    QUEUE_TABLES,
    OperationsQueue,
    QueueTable,
    ResourceType,
)
from signalscope.domain.tenancy.policy import ContentAccessPolicy

JOB_NOT_FOUND = "Failed job was not found."
NOT_FAILED = "Only a failed job can be retried."


@dataclass(frozen=True, slots=True)
class RetriedJob:
    """A failed job that was put back in its queue."""

    queue: OperationsQueue
    job_id: uuid.UUID
    status: str
    resource_type: ResourceType
    resource_id: uuid.UUID
    attempt_count: int
    available_at: datetime


class FailedJobRetryService:
    """Puts one failed job of an organization back in its queue.

    Retry is a queue operation, not a status flip: it leaves the job pending
    and available now, with its leases cleared, exactly as recovering a stale
    job does. The attempt count is kept, so the next claim counts as the next
    attempt. Only a job that is still failed can be retried, so work that is
    already pending or running is never queued twice. Writes commit before
    they return, together with an audit event, so there is never a retry
    without its record.
    """

    def __init__(self, session: AsyncSession, policy: ContentAccessPolicy) -> None:
        self.session = session
        self.policy = policy

    async def retry(
        self, organization_id: uuid.UUID, queue: OperationsQueue, job_id: uuid.UUID, now: datetime
    ) -> RetriedJob:
        scope = await operations_scope(self.policy, organization_id)
        table = QUEUE_TABLES[queue]
        model = table.model
        job = (
            await self.session.scalars(
                select(model)
                .where(model.id == job_id, table.in_scope(scope))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if job is None:
            await self.session.rollback()
            raise NotFoundError(JOB_NOT_FOUND)
        if job.status is not table.status("failed"):
            await self.session.rollback()
            raise ConflictError(NOT_FAILED)
        _requeue(job, table, now)
        if isinstance(job, IngestionJob):
            await self._fresh_ingestion_run(job)
        # operations_scope refuses to run without an actor, so there is one.
        assert self.policy.actor is not None
        SecurityAuditService(self.session).record(
            AuditAction.JOB_RETRIED,
            actor_user_id=self.policy.actor.id,
            resource_type="operations_job",
            resource_id=job_id,
            organization_id=organization_id,
            details={"queue": queue.value, "attempt_count": job.attempt_count},
        )
        await self.session.commit()
        return RetriedJob(
            queue=queue,
            job_id=job_id,
            status=str(job.status),
            resource_type=table.resource_type,
            resource_id=getattr(job, table.resource_column),
            attempt_count=job.attempt_count,
            available_at=job.available_at,
        )

    async def _fresh_ingestion_run(self, job: IngestionJob) -> None:
        """Point a retried ingestion job at a new pending run.

        An ingestion run cannot start twice: the failed job's run is already
        in a terminal state, and a worker can only start a pending run. The
        job gets a fresh pending run, the same as when a stale job is
        recovered, and the failed run stays in the history.
        """
        runs = IngestionRunRepository(self.session)
        run = await runs.get_for_update(job.run_id)
        if run is not None and run.status is IngestionStatus.PENDING:
            return
        new_run = await runs.add(
            IngestionRun(source_id=job.source_id, status=IngestionStatus.PENDING)
        )
        job.run_id = new_run.id


def _requeue(job: object, table: QueueTable, now: datetime) -> None:
    """Make a failed job pending and available now, with its lease cleared.

    The attempt count and last error are left as they are, the same as when a
    worker recovers a stale job. The last error stays until the job runs again.
    """
    job.status = table.status("pending")  # type: ignore[attr-defined]
    job.available_at = now  # type: ignore[attr-defined]
    job.claimed_at = None  # type: ignore[attr-defined]
    job.heartbeat_at = None  # type: ignore[attr-defined]
    job.lease_expires_at = None  # type: ignore[attr-defined]
    job.lease_token = None  # type: ignore[attr-defined]
    job.finished_at = None  # type: ignore[attr-defined]
