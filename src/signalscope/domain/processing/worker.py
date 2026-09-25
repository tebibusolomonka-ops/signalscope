import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import SignalScopeError
from signalscope.domain.processing.job_repository import DocumentProcessingJobRepository
from signalscope.domain.processing.model import DocumentProcessingJob
from signalscope.domain.processing.processor import DocumentProcessor
from signalscope.domain.sources.scheduling import Clock, utc_now

logger = logging.getLogger(__name__)

UNEXPECTED_PROCESSING_ERROR = "Document processing failed with an unexpected error."


@dataclass(frozen=True, slots=True)
class ProcessingWorkerResult:
    """What one pass of the worker did. job is None when there was no work."""

    job: DocumentProcessingJob | None


class DocumentProcessingWorker:
    """Takes one queued document processing job and runs it.

    The claim is committed before the file is read, so no database transaction
    or row lock stays open while the file is parsed.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        processor: DocumentProcessor,
        clock: Clock = utc_now,
    ) -> None:
        self.session_factory = session_factory
        self.processor = processor
        self.clock = clock

    async def run_once(self) -> ProcessingWorkerResult:
        job = await self._claim()
        if job is None:
            return ProcessingWorkerResult(job=None)
        try:
            await self.processor.process(job.asset_id)
        except SignalScopeError as error:
            # These messages are written for people, such as "PDF is encrypted."
            logger.warning("Document processing job %s failed: %s", job.id, error)
            return ProcessingWorkerResult(job=await self._mark_failed(job.id, str(error)))
        except Exception:
            logger.exception("Document processing job %s failed", job.id)
            return ProcessingWorkerResult(
                job=await self._mark_failed(job.id, UNEXPECTED_PROCESSING_ERROR)
            )
        return ProcessingWorkerResult(job=await self._mark_completed(job.id))

    async def _claim(self) -> DocumentProcessingJob | None:
        async with self.session_factory() as session:
            job = await DocumentProcessingJobRepository(session).claim_next(self.clock())
            await session.commit()
        return job

    async def _mark_completed(self, job_id: uuid.UUID) -> DocumentProcessingJob:
        async with self.session_factory() as session:
            job = await DocumentProcessingJobRepository(session).mark_completed(
                job_id, self.clock()
            )
            await session.commit()
        return job

    async def _mark_failed(self, job_id: uuid.UUID, error: str) -> DocumentProcessingJob:
        async with self.session_factory() as session:
            job = await DocumentProcessingJobRepository(session).mark_failed(
                job_id, self.clock(), error
            )
            await session.commit()
        return job
