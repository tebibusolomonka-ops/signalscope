import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, NotFoundError, short_error_message
from signalscope.core.leases import DEFAULT_LEASE_POLICY, LeasePolicy
from signalscope.domain.ingestion.model import IngestionJob, IngestionJobStatus


class InvalidJobStatusChangeError(ConflictError):
    default_message = "Ingestion job cannot change to that status."


class IngestionJobRepository:
    """Database access for ingestion jobs.

    It never commits. The caller decides when the transaction ends.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, job: IngestionJob) -> IngestionJob:
        self.session.add(job)
        # Flush so the database fills in the timestamps and reports errors now.
        await self.session.flush()
        return job

    async def get(self, job_id: uuid.UUID) -> IngestionJob | None:
        return await self.session.get(IngestionJob, job_id)

    async def claim_next(
        self, now: datetime, lease: LeasePolicy = DEFAULT_LEASE_POLICY
    ) -> IngestionJob | None:
        """Claim the pending job that has been available longest.

        Returns None when no job is available. Rows locked by another
        transaction are skipped, so two workers never claim the same job. The
        caller should commit soon, because the row stays locked until then.
        The claimed job gets a lease that ends lease.duration after now.
        """
        result = await self.session.scalars(
            select(IngestionJob)
            .where(
                IngestionJob.status == IngestionJobStatus.PENDING,
                IngestionJob.available_at <= now,
            )
            .order_by(IngestionJob.available_at, IngestionJob.created_at, IngestionJob.id)
            .limit(1)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        job = result.one_or_none()
        if job is None:
            return None
        job.status = IngestionJobStatus.RUNNING
        job.claimed_at = now
        job.heartbeat_at = now
        job.lease_expires_at = lease.expires_at(now)
        # The row is locked, so no other transaction can change the count meanwhile.
        job.attempt_count += 1
        await self.session.flush()
        return job

    async def mark_completed(self, job_id: uuid.UUID, now: datetime) -> IngestionJob:
        return await self._finish(job_id, IngestionJobStatus.COMPLETED, now)

    async def mark_failed(self, job_id: uuid.UUID, now: datetime, error: str) -> IngestionJob:
        """Mark a job as failed with a short message for people, not a traceback."""
        return await self._finish(
            job_id, IngestionJobStatus.FAILED, now, last_error=short_error_message(error)
        )

    async def _finish(
        self,
        job_id: uuid.UUID,
        status: IngestionJobStatus,
        now: datetime,
        last_error: str | None = None,
    ) -> IngestionJob:
        result = await self.session.scalars(
            select(IngestionJob)
            .where(IngestionJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        job = result.one_or_none()
        if job is None:
            raise NotFoundError("Ingestion job was not found.")
        if job.status is not IngestionJobStatus.RUNNING:
            raise InvalidJobStatusChangeError(
                f"Ingestion job is {job.status} and cannot become {status}."
            )
        job.status = status
        job.finished_at = now
        job.last_error = last_error
        # A finished job is no longer held, so it can never look stale.
        job.lease_expires_at = None
        await self.session.flush()
        return job
