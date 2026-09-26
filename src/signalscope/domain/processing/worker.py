import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import SignalScopeError
from signalscope.core.leases import DEFAULT_LEASE_POLICY, JobNotHeldError, LeasePolicy
from signalscope.domain.processing.job_repository import DocumentProcessingJobRepository
from signalscope.domain.processing.model import DocumentProcessingJob
from signalscope.domain.processing.processor import DocumentProcessor
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.workers.heartbeat import Sleep, keep_lease_alive

logger = logging.getLogger(__name__)

UNEXPECTED_PROCESSING_ERROR = "Document processing failed with an unexpected error."


@dataclass(frozen=True, slots=True)
class ProcessingWorkerResult:
    """What one pass of the worker did. job is None when there was no work.

    lease_lost means another worker took the job over while it was running, so
    this worker left the job alone.
    """

    job: DocumentProcessingJob | None
    lease_lost: bool = False


class DocumentProcessingWorker:
    """Takes one queued document processing job and runs it.

    The claim is committed before the file is read, so no database transaction
    or row lock stays open while the file is parsed. The lease is extended in
    the background until parsing has finished.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        processor: DocumentProcessor,
        clock: Clock = utc_now,
        lease: LeasePolicy = DEFAULT_LEASE_POLICY,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.session_factory = session_factory
        self.processor = processor
        self.clock = clock
        self.lease = lease
        self.sleep = sleep

    async def run_once(self) -> ProcessingWorkerResult:
        job = await self._claim()
        if job is None:
            return ProcessingWorkerResult(job=None)
        token = job.lease_token
        # Every claim sets a token.
        assert token is not None
        async with keep_lease_alive(
            lambda: self._heartbeat(job.id, token), self.lease, self.sleep
        ) as keeper:
            error = await self._process(job)
        try:
            if keeper.lost:
                raise JobNotHeldError()
            if error is not None:
                return ProcessingWorkerResult(job=await self._mark_failed(job.id, token, error))
            return ProcessingWorkerResult(job=await self._mark_completed(job.id, token))
        except JobNotHeldError:
            logger.warning("Document processing job %s was taken over by another worker", job.id)
            return ProcessingWorkerResult(job=job, lease_lost=True)

    async def _process(self, job: DocumentProcessingJob) -> str | None:
        """Parse the file and return the error to store, or None when it worked."""
        try:
            await self.processor.process(job.asset_id)
        except SignalScopeError as error:
            # These messages are written for people, such as "PDF is encrypted."
            logger.warning("Document processing job %s failed: %s", job.id, error)
            return str(error)
        except Exception:
            logger.exception("Document processing job %s failed", job.id)
            return UNEXPECTED_PROCESSING_ERROR
        return None

    async def _claim(self) -> DocumentProcessingJob | None:
        async with self.session_factory() as session:
            job = await DocumentProcessingJobRepository(session).claim_next(
                self.clock(), self.lease
            )
            await session.commit()
        return job

    async def _heartbeat(self, job_id: uuid.UUID, token: uuid.UUID) -> bool:
        async with self.session_factory() as session:
            held = await DocumentProcessingJobRepository(session).heartbeat(
                job_id, token, self.clock(), self.lease
            )
            await session.commit()
        return held

    async def _mark_completed(self, job_id: uuid.UUID, token: uuid.UUID) -> DocumentProcessingJob:
        async with self.session_factory() as session:
            job = await DocumentProcessingJobRepository(session).mark_completed(
                job_id, token, self.clock()
            )
            await session.commit()
        return job

    async def _mark_failed(
        self, job_id: uuid.UUID, token: uuid.UUID, error: str
    ) -> DocumentProcessingJob:
        async with self.session_factory() as session:
            job = await DocumentProcessingJobRepository(session).mark_failed(
                job_id, token, self.clock(), error
            )
            await session.commit()
        return job
