import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import NotFoundError, short_error_message
from signalscope.core.leases import DEFAULT_LEASE_POLICY, JobNotHeldError, LeasePolicy
from signalscope.domain.claims.job import ClaimExtractionJob, ClaimExtractionJobStatus
from signalscope.domain.operations.attempt import OperationAttemptOutcome, OperationAttemptQueue
from signalscope.domain.operations.attempts import finish_attempt, start_chunk_attempt


class InvalidClaimExtractionJobStatusChangeError(JobNotHeldError):
    default_message = "Claim extraction job cannot change to that status."


class ClaimExtractionJobRepository:
    """Database access for claim extraction jobs.

    It never commits. The caller decides when the transaction ends.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, job: ClaimExtractionJob) -> ClaimExtractionJob:
        self.session.add(job)
        # Flush so the database fills in the defaults and reports errors now.
        await self.session.flush()
        return job

    async def get(self, job_id: uuid.UUID) -> ClaimExtractionJob | None:
        return await self.session.get(ClaimExtractionJob, job_id)

    async def claim_next(
        self,
        now: datetime,
        models: Sequence[tuple[str, str]],
        lease: LeasePolicy = DEFAULT_LEASE_POLICY,
    ) -> ClaimExtractionJob | None:
        """Claim the pending job that has been available longest.

        Only jobs for one of models, as (provider, model) pairs, are claimed,
        because a worker can only run the models it has. Rows locked by another
        transaction are skipped, so two workers never claim the same job. The
        caller should commit soon, because the row stays locked until then.
        """
        if not models:
            return None
        result = await self.session.scalars(
            select(ClaimExtractionJob)
            .where(
                ClaimExtractionJob.status == ClaimExtractionJobStatus.PENDING,
                ClaimExtractionJob.available_at <= now,
                tuple_(ClaimExtractionJob.provider, ClaimExtractionJob.model).in_(list(models)),
            )
            .order_by(
                ClaimExtractionJob.available_at,
                ClaimExtractionJob.created_at,
                ClaimExtractionJob.id,
            )
            .limit(1)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        job = result.one_or_none()
        if job is None:
            return None
        _start(job, now, lease)
        await start_chunk_attempt(
            self.session,
            queue=OperationAttemptQueue.CLAIM,
            job_id=job.id,
            attempt_number=job.attempt_count,
            chunk_id=job.chunk_id,
            started_at=now,
        )
        await self.session.flush()
        return job

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
            update(ClaimExtractionJob)
            .where(
                ClaimExtractionJob.id == job_id,
                ClaimExtractionJob.status == ClaimExtractionJobStatus.RUNNING,
                ClaimExtractionJob.lease_token == lease_token,
            )
            .values(heartbeat_at=now, lease_expires_at=lease.expires_at(now))
            .returning(ClaimExtractionJob.id)
        )
        return result.scalar_one_or_none() is not None

    async def recover_stale(self, now: datetime, limit: int) -> list[ClaimExtractionJob]:
        """Put running jobs whose lease ran out back in the queue.

        Their worker is taken to be gone. Extracting from a chunk again replaces
        its claims, so the jobs simply become pending and available at now.
        attempt_count and last_error stay as they are. Rows locked by another
        transaction are skipped, so two recoveries never take the same job.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        result = await self.session.scalars(
            select(ClaimExtractionJob)
            .where(
                ClaimExtractionJob.status == ClaimExtractionJobStatus.RUNNING,
                ClaimExtractionJob.lease_expires_at <= now,
            )
            .order_by(ClaimExtractionJob.lease_expires_at, ClaimExtractionJob.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        jobs = list(result.all())
        for job in jobs:
            await finish_attempt(
                self.session,
                queue=OperationAttemptQueue.CLAIM,
                job_id=job.id,
                attempt_number=job.attempt_count,
                outcome=OperationAttemptOutcome.RECOVERED,
                finished_at=now,
                error="Worker lease expired.",
            )
            job.status = ClaimExtractionJobStatus.PENDING
            job.available_at = now
            job.claimed_at = None
            job.heartbeat_at = None
            job.lease_expires_at = None
            job.lease_token = None
        await self.session.flush()
        return jobs

    async def mark_completed(
        self, job_id: uuid.UUID, lease_token: uuid.UUID, now: datetime
    ) -> ClaimExtractionJob:
        return await self._finish(job_id, lease_token, ClaimExtractionJobStatus.COMPLETED, now)

    async def mark_failed(
        self, job_id: uuid.UUID, lease_token: uuid.UUID, now: datetime, error: str
    ) -> ClaimExtractionJob:
        """Mark a job as failed with a short message for people, not a traceback."""
        return await self._finish(
            job_id,
            lease_token,
            ClaimExtractionJobStatus.FAILED,
            now,
            last_error=short_error_message(error),
        )

    async def _finish(
        self,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        status: ClaimExtractionJobStatus,
        now: datetime,
        last_error: str | None = None,
    ) -> ClaimExtractionJob:
        result = await self.session.scalars(
            select(ClaimExtractionJob)
            .where(ClaimExtractionJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        job = result.one_or_none()
        if job is None:
            raise NotFoundError("Claim extraction job was not found.")
        if job.status is not ClaimExtractionJobStatus.RUNNING:
            raise InvalidClaimExtractionJobStatusChangeError(
                f"Claim extraction job is {job.status} and cannot become {status}."
            )
        if job.lease_token != lease_token:
            raise JobNotHeldError()
        job.status = status
        job.finished_at = now
        job.last_error = last_error
        await finish_attempt(
            self.session,
            queue=OperationAttemptQueue.CLAIM,
            job_id=job.id,
            attempt_number=job.attempt_count,
            outcome=OperationAttemptOutcome.SUCCEEDED
            if status is ClaimExtractionJobStatus.COMPLETED
            else OperationAttemptOutcome.FAILED,
            finished_at=now,
            error=last_error,
        )
        # A finished job is no longer held, so it can never look stale.
        job.lease_expires_at = None
        job.lease_token = None
        await self.session.flush()
        return job


def _start(job: ClaimExtractionJob, now: datetime, lease: LeasePolicy) -> None:
    job.status = ClaimExtractionJobStatus.RUNNING
    job.claimed_at = now
    job.heartbeat_at = now
    job.lease_expires_at = lease.expires_at(now)
    job.lease_token = uuid.uuid4()
    job.finished_at = None
    # The row is locked, so no other transaction can change the count meanwhile.
    job.attempt_count += 1
