import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import NotFoundError, short_error_message
from signalscope.core.leases import DEFAULT_LEASE_POLICY, JobNotHeldError, LeasePolicy
from signalscope.domain.entities.job import EntityExtractionJob, EntityExtractionJobStatus


class InvalidEntityExtractionJobStatusChangeError(JobNotHeldError):
    default_message = "Entity extraction job cannot change to that status."


class EntityExtractionJobRepository:
    """Database access for entity extraction jobs.

    It never commits. The caller decides when the transaction ends.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, job: EntityExtractionJob) -> EntityExtractionJob:
        self.session.add(job)
        # Flush so the database fills in the defaults and reports errors now.
        await self.session.flush()
        return job

    async def get(self, job_id: uuid.UUID) -> EntityExtractionJob | None:
        return await self.session.get(EntityExtractionJob, job_id)

    async def claim_next(
        self,
        now: datetime,
        models: Sequence[tuple[str, str]],
        lease: LeasePolicy = DEFAULT_LEASE_POLICY,
    ) -> EntityExtractionJob | None:
        """Claim the pending job that has been available longest.

        Only jobs for one of models, as (provider, model) pairs, are claimed,
        because a worker can only run the models it has. Rows locked by another
        transaction are skipped, so two workers never claim the same job. The
        caller should commit soon, because the row stays locked until then.
        """
        if not models:
            return None
        result = await self.session.scalars(
            select(EntityExtractionJob)
            .where(
                EntityExtractionJob.status == EntityExtractionJobStatus.PENDING,
                EntityExtractionJob.available_at <= now,
                tuple_(EntityExtractionJob.provider, EntityExtractionJob.model).in_(list(models)),
            )
            .order_by(
                EntityExtractionJob.available_at,
                EntityExtractionJob.created_at,
                EntityExtractionJob.id,
            )
            .limit(1)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        job = result.one_or_none()
        if job is None:
            return None
        _start(job, now, lease)
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
            update(EntityExtractionJob)
            .where(
                EntityExtractionJob.id == job_id,
                EntityExtractionJob.status == EntityExtractionJobStatus.RUNNING,
                EntityExtractionJob.lease_token == lease_token,
            )
            .values(heartbeat_at=now, lease_expires_at=lease.expires_at(now))
            .returning(EntityExtractionJob.id)
        )
        return result.scalar_one_or_none() is not None

    async def recover_stale(self, now: datetime, limit: int) -> list[EntityExtractionJob]:
        """Put running jobs whose lease ran out back in the queue.

        Their worker is taken to be gone. Extracting from a chunk again replaces
        its mentions, so the jobs simply become pending and available at now.
        attempt_count and last_error stay as they are. Rows locked by another
        transaction are skipped, so two recoveries never take the same job.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        result = await self.session.scalars(
            select(EntityExtractionJob)
            .where(
                EntityExtractionJob.status == EntityExtractionJobStatus.RUNNING,
                EntityExtractionJob.lease_expires_at <= now,
            )
            .order_by(EntityExtractionJob.lease_expires_at, EntityExtractionJob.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        jobs = list(result.all())
        for job in jobs:
            job.status = EntityExtractionJobStatus.PENDING
            job.available_at = now
            job.claimed_at = None
            job.heartbeat_at = None
            job.lease_expires_at = None
            job.lease_token = None
        await self.session.flush()
        return jobs

    async def mark_completed(
        self, job_id: uuid.UUID, lease_token: uuid.UUID, now: datetime
    ) -> EntityExtractionJob:
        return await self._finish(job_id, lease_token, EntityExtractionJobStatus.COMPLETED, now)

    async def mark_failed(
        self, job_id: uuid.UUID, lease_token: uuid.UUID, now: datetime, error: str
    ) -> EntityExtractionJob:
        """Mark a job as failed with a short message for people, not a traceback."""
        return await self._finish(
            job_id,
            lease_token,
            EntityExtractionJobStatus.FAILED,
            now,
            last_error=short_error_message(error),
        )

    async def _finish(
        self,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        status: EntityExtractionJobStatus,
        now: datetime,
        last_error: str | None = None,
    ) -> EntityExtractionJob:
        result = await self.session.scalars(
            select(EntityExtractionJob)
            .where(EntityExtractionJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        job = result.one_or_none()
        if job is None:
            raise NotFoundError("Entity extraction job was not found.")
        if job.status is not EntityExtractionJobStatus.RUNNING:
            raise InvalidEntityExtractionJobStatusChangeError(
                f"Entity extraction job is {job.status} and cannot become {status}."
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


def _start(job: EntityExtractionJob, now: datetime, lease: LeasePolicy) -> None:
    job.status = EntityExtractionJobStatus.RUNNING
    job.claimed_at = now
    job.heartbeat_at = now
    job.lease_expires_at = lease.expires_at(now)
    job.lease_token = uuid.uuid4()
    job.finished_at = None
    # The row is locked, so no other transaction can change the count meanwhile.
    job.attempt_count += 1
