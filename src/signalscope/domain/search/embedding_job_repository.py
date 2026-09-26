import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import NotFoundError, short_error_message
from signalscope.core.leases import DEFAULT_LEASE_POLICY, JobNotHeldError, LeasePolicy
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus

# Enough for a few model batches, small enough to keep the claim short.
MAX_BATCH_CLAIM = 256


class InvalidEmbeddingJobStatusChangeError(JobNotHeldError):
    default_message = "Embedding job cannot change to that status."


class EmbeddingJobRepository:
    """Database access for embedding jobs.

    It never commits. The caller decides when the transaction ends.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, job: EmbeddingJob) -> EmbeddingJob:
        self.session.add(job)
        # Flush so the database fills in the defaults and reports errors now.
        await self.session.flush()
        return job

    async def get(self, job_id: uuid.UUID) -> EmbeddingJob | None:
        return await self.session.get(EmbeddingJob, job_id)

    async def claim_batch(
        self,
        now: datetime,
        provider: str,
        model: str,
        limit: int,
        lease: LeasePolicy = DEFAULT_LEASE_POLICY,
    ) -> list[EmbeddingJob]:
        """Claim up to limit pending jobs of one model, available longest first.

        One model can embed all of them in one call. Rows locked by another
        transaction are skipped, so two workers never claim the same job. Each
        job gets its own lease token. The caller should commit soon, because
        the rows stay locked until then.
        """
        if not 1 <= limit <= MAX_BATCH_CLAIM:
            raise ValueError(f"limit must be between 1 and {MAX_BATCH_CLAIM}")
        result = await self.session.scalars(
            select(EmbeddingJob)
            .where(
                EmbeddingJob.status == EmbeddingJobStatus.PENDING,
                EmbeddingJob.available_at <= now,
                EmbeddingJob.provider == provider,
                EmbeddingJob.model == model,
            )
            .order_by(EmbeddingJob.available_at, EmbeddingJob.created_at, EmbeddingJob.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        jobs = list(result.all())
        for job in jobs:
            _start(job, now, lease)
        await self.session.flush()
        return jobs

    async def heartbeat(
        self,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        now: datetime,
        lease: LeasePolicy = DEFAULT_LEASE_POLICY,
    ) -> bool:
        """Extend the lease of a running job.

        Returns False when there is no running job with that ID and lease
        token, for example because it finished, or was recovered after its
        lease ran out and maybe claimed again. The worker has then lost the
        job and should stop working on it.
        """
        result = await self.session.execute(
            update(EmbeddingJob)
            .where(
                EmbeddingJob.id == job_id,
                EmbeddingJob.status == EmbeddingJobStatus.RUNNING,
                EmbeddingJob.lease_token == lease_token,
            )
            .values(heartbeat_at=now, lease_expires_at=lease.expires_at(now))
            .returning(EmbeddingJob.id)
        )
        return result.scalar_one_or_none() is not None

    async def recover_stale(self, now: datetime, limit: int) -> list[EmbeddingJob]:
        """Put running jobs whose lease ran out back in the queue.

        Their worker is taken to be gone. Embedding a chunk again replaces its
        vector, so the jobs simply become pending and available at now.
        attempt_count and last_error stay as they are. Rows locked by another
        transaction are skipped, so two recoveries never take the same job.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        result = await self.session.scalars(
            select(EmbeddingJob)
            .where(
                EmbeddingJob.status == EmbeddingJobStatus.RUNNING,
                EmbeddingJob.lease_expires_at <= now,
            )
            .order_by(EmbeddingJob.lease_expires_at, EmbeddingJob.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        jobs = list(result.all())
        for job in jobs:
            job.status = EmbeddingJobStatus.PENDING
            job.available_at = now
            job.claimed_at = None
            job.heartbeat_at = None
            job.lease_expires_at = None
            job.lease_token = None
        await self.session.flush()
        return jobs

    async def mark_completed(
        self, job_id: uuid.UUID, lease_token: uuid.UUID, now: datetime
    ) -> EmbeddingJob:
        return await self._finish(job_id, lease_token, EmbeddingJobStatus.COMPLETED, now)

    async def mark_failed(
        self, job_id: uuid.UUID, lease_token: uuid.UUID, now: datetime, error: str
    ) -> EmbeddingJob:
        """Mark a job as failed with a short message for people, not a traceback."""
        return await self._finish(
            job_id,
            lease_token,
            EmbeddingJobStatus.FAILED,
            now,
            last_error=short_error_message(error),
        )

    async def _finish(
        self,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        status: EmbeddingJobStatus,
        now: datetime,
        last_error: str | None = None,
    ) -> EmbeddingJob:
        result = await self.session.scalars(
            select(EmbeddingJob)
            .where(EmbeddingJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        job = result.one_or_none()
        if job is None:
            raise NotFoundError("Embedding job was not found.")
        if job.status is not EmbeddingJobStatus.RUNNING:
            raise InvalidEmbeddingJobStatusChangeError(
                f"Embedding job is {job.status} and cannot become {status}."
            )
        if job.lease_token != lease_token:
            raise JobNotHeldError()
        job.status = status
        job.finished_at = now
        job.last_error = last_error
        # A finished job is no longer held, so it can never look stale.
        job.lease_expires_at = None
        job.lease_token = None
        await self.session.flush()
        return job


def _start(job: EmbeddingJob, now: datetime, lease: LeasePolicy) -> None:
    job.status = EmbeddingJobStatus.RUNNING
    job.claimed_at = now
    job.heartbeat_at = now
    job.lease_expires_at = lease.expires_at(now)
    job.lease_token = uuid.uuid4()
    job.finished_at = None
    # The row is locked, so no other transaction can change the count meanwhile.
    job.attempt_count += 1
