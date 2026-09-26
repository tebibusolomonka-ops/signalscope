import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, NotFoundError, short_error_message
from signalscope.core.leases import DEFAULT_LEASE_POLICY, LeasePolicy
from signalscope.domain.processing.model import DocumentProcessingJob, ProcessingJobStatus


class InvalidProcessingJobStatusChangeError(ConflictError):
    default_message = "Document processing job cannot change to that status."


class DocumentProcessingJobRepository:
    """Database access for document processing jobs.

    It never commits. The caller decides when the transaction ends.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, job: DocumentProcessingJob) -> DocumentProcessingJob:
        self.session.add(job)
        # Flush so the database fills in the defaults and reports errors now.
        await self.session.flush()
        return job

    async def get(self, job_id: uuid.UUID) -> DocumentProcessingJob | None:
        return await self.session.get(DocumentProcessingJob, job_id)

    async def claim_next(
        self, now: datetime, lease: LeasePolicy = DEFAULT_LEASE_POLICY
    ) -> DocumentProcessingJob | None:
        """Claim the pending job that has been available longest.

        Returns None when no job is available. Rows locked by another
        transaction are skipped, so two workers never claim the same job. The
        caller should commit soon, because the row stays locked until then.
        The claimed job gets a lease that ends lease.duration after now.
        """
        result = await self.session.scalars(
            select(DocumentProcessingJob)
            .where(
                DocumentProcessingJob.status == ProcessingJobStatus.PENDING,
                DocumentProcessingJob.available_at <= now,
            )
            .order_by(
                DocumentProcessingJob.available_at,
                DocumentProcessingJob.created_at,
                DocumentProcessingJob.id,
            )
            .limit(1)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        job = result.one_or_none()
        if job is None:
            return None
        job.status = ProcessingJobStatus.RUNNING
        job.claimed_at = now
        job.heartbeat_at = now
        job.lease_expires_at = lease.expires_at(now)
        # The row is locked, so no other transaction can change the count meanwhile.
        job.attempt_count += 1
        await self.session.flush()
        return job

    async def recover_stale(self, now: datetime, limit: int) -> list[DocumentProcessingJob]:
        """Put running jobs whose lease ran out back in the queue.

        Their worker is taken to be gone. Processing a file again replaces its
        earlier results, so the jobs simply become pending and available at
        now. attempt_count and last_error stay as they are. Rows locked by
        another transaction are skipped, so two recoveries never take the
        same job.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        result = await self.session.scalars(
            select(DocumentProcessingJob)
            .where(
                DocumentProcessingJob.status == ProcessingJobStatus.RUNNING,
                DocumentProcessingJob.lease_expires_at <= now,
            )
            .order_by(DocumentProcessingJob.lease_expires_at, DocumentProcessingJob.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        jobs = list(result.all())
        for job in jobs:
            job.status = ProcessingJobStatus.PENDING
            job.available_at = now
            job.claimed_at = None
            job.heartbeat_at = None
            job.lease_expires_at = None
        await self.session.flush()
        return jobs

    async def mark_completed(self, job_id: uuid.UUID, now: datetime) -> DocumentProcessingJob:
        return await self._finish(job_id, ProcessingJobStatus.COMPLETED, now)

    async def mark_failed(
        self, job_id: uuid.UUID, now: datetime, error: str
    ) -> DocumentProcessingJob:
        """Mark a job as failed with a short message for people, not a traceback."""
        return await self._finish(
            job_id, ProcessingJobStatus.FAILED, now, last_error=short_error_message(error)
        )

    async def _finish(
        self,
        job_id: uuid.UUID,
        status: ProcessingJobStatus,
        now: datetime,
        last_error: str | None = None,
    ) -> DocumentProcessingJob:
        result = await self.session.scalars(
            select(DocumentProcessingJob)
            .where(DocumentProcessingJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        job = result.one_or_none()
        if job is None:
            raise NotFoundError("Document processing job was not found.")
        if job.status is not ProcessingJobStatus.RUNNING:
            raise InvalidProcessingJobStatusChangeError(
                f"Document processing job is {job.status} and cannot become {status}."
            )
        job.status = status
        job.finished_at = now
        job.last_error = last_error
        # A finished job is no longer held, so it can never look stale.
        job.lease_expires_at = None
        await self.session.flush()
        return job
