import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.leases import DEFAULT_LEASE_POLICY, JobNotHeldError, LeasePolicy
from signalscope.domain.ingestion.executor import IngestionExecutor
from signalscope.domain.ingestion.job_repository import IngestionJobRepository
from signalscope.domain.ingestion.model import IngestionJob, IngestionRun, IngestionStatus
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.workers.heartbeat import Sleep, keep_lease_alive

logger = logging.getLogger(__name__)

UNEXPECTED_JOB_ERROR = "Ingestion job failed with an unexpected error."


@dataclass(frozen=True, slots=True)
class WorkerResult:
    """What one pass of the worker did. job is None when there was no work.

    lease_lost means another worker took the job over while it was running, so
    this worker left the job alone.
    """

    job: IngestionJob | None
    run: IngestionRun | None = None
    lease_lost: bool = False


class IngestionWorker:
    """Takes one queued ingestion job and runs it.

    The claim is committed before any fetching starts, so no database
    transaction or row lock stays open while the executor waits on the network.
    The lease is extended in the background until the run has finished.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        executor: IngestionExecutor,
        clock: Clock = utc_now,
        lease: LeasePolicy = DEFAULT_LEASE_POLICY,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.session_factory = session_factory
        self.executor = executor
        self.clock = clock
        self.lease = lease
        self.sleep = sleep

    async def run_once(self) -> WorkerResult:
        job = await self._claim()
        if job is None:
            return WorkerResult(job=None)
        token = job.lease_token
        # Every claim sets a token.
        assert token is not None
        async with keep_lease_alive(
            lambda: self._heartbeat(job.id, token), self.lease, self.sleep
        ) as keeper:
            run, error = await self._execute(job)
        try:
            if keeper.lost:
                raise JobNotHeldError()
            if error is not None:
                return WorkerResult(job=await self._mark_failed(job.id, token, error), run=run)
            return WorkerResult(job=await self._mark_completed(job.id, token), run=run)
        except JobNotHeldError:
            logger.warning("Ingestion job %s was taken over by another worker", job.id)
            return WorkerResult(job=job, run=run, lease_lost=True)

    async def _execute(self, job: IngestionJob) -> tuple[IngestionRun | None, str | None]:
        """Run the job and return its run and the error to store, if any."""
        try:
            run = await self.executor.execute(job.run_id)
        except Exception:
            logger.exception("Ingestion job %s failed", job.id)
            return None, UNEXPECTED_JOB_ERROR
        if run.status is IngestionStatus.COMPLETED:
            return run, None
        return run, run.error_message or "Ingestion failed."

    async def _claim(self) -> IngestionJob | None:
        async with self.session_factory() as session:
            job = await IngestionJobRepository(session).claim_next(self.clock(), self.lease)
            await session.commit()
        return job

    async def _heartbeat(self, job_id: uuid.UUID, token: uuid.UUID) -> bool:
        async with self.session_factory() as session:
            held = await IngestionJobRepository(session).heartbeat(
                job_id, token, self.clock(), self.lease
            )
            await session.commit()
        return held

    async def _mark_completed(self, job_id: uuid.UUID, token: uuid.UUID) -> IngestionJob:
        async with self.session_factory() as session:
            job = await IngestionJobRepository(session).mark_completed(job_id, token, self.clock())
            await session.commit()
        return job

    async def _mark_failed(self, job_id: uuid.UUID, token: uuid.UUID, error: str) -> IngestionJob:
        async with self.session_factory() as session:
            job = await IngestionJobRepository(session).mark_failed(
                job_id, token, self.clock(), error
            )
            await session.commit()
        return job
