import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.ingestion.executor import IngestionExecutor
from signalscope.domain.ingestion.job_repository import IngestionJobRepository
from signalscope.domain.ingestion.model import IngestionJob, IngestionRun, IngestionStatus
from signalscope.domain.sources.scheduling import Clock, utc_now

logger = logging.getLogger(__name__)

UNEXPECTED_JOB_ERROR = "Ingestion job failed with an unexpected error."


@dataclass(frozen=True, slots=True)
class WorkerResult:
    """What one pass of the worker did. job is None when there was no work."""

    job: IngestionJob | None
    run: IngestionRun | None = None


class IngestionWorker:
    """Takes one queued ingestion job and runs it.

    The claim is committed before any fetching starts, so no database
    transaction or row lock stays open while the executor waits on the network.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        executor: IngestionExecutor,
        clock: Clock = utc_now,
    ) -> None:
        self.session_factory = session_factory
        self.executor = executor
        self.clock = clock

    async def run_once(self) -> WorkerResult:
        job = await self._claim()
        if job is None:
            return WorkerResult(job=None)
        try:
            run = await self.executor.execute(job.run_id)
        except Exception:
            logger.exception("Ingestion job %s failed", job.id)
            return WorkerResult(job=await self._mark_failed(job.id, UNEXPECTED_JOB_ERROR))
        if run.status is IngestionStatus.COMPLETED:
            return WorkerResult(job=await self._mark_completed(job.id), run=run)
        error = run.error_message or "Ingestion failed."
        return WorkerResult(job=await self._mark_failed(job.id, error), run=run)

    async def _claim(self) -> IngestionJob | None:
        async with self.session_factory() as session:
            job = await IngestionJobRepository(session).claim_next(self.clock())
            await session.commit()
        return job

    async def _mark_completed(self, job_id: uuid.UUID) -> IngestionJob:
        async with self.session_factory() as session:
            job = await IngestionJobRepository(session).mark_completed(job_id, self.clock())
            await session.commit()
        return job

    async def _mark_failed(self, job_id: uuid.UUID, error: str) -> IngestionJob:
        async with self.session_factory() as session:
            job = await IngestionJobRepository(session).mark_failed(job_id, self.clock(), error)
            await session.commit()
        return job
