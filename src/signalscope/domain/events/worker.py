import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import SignalScopeError
from signalscope.core.leases import DEFAULT_LEASE_POLICY, LeasePolicy
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.events.job import EventExtractionJob, EventExtractionJobStatus
from signalscope.domain.events.job_repository import EventExtractionJobRepository
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.events.provider import ExtractedEvent, extract_events
from signalscope.events.registry import EventExtractorRegistry
from signalscope.workers.heartbeat import Sleep, keep_lease_alive

logger = logging.getLogger(__name__)

UNEXPECTED_EXTRACTION_ERROR = "Event extraction failed with an unexpected error."


@dataclass(frozen=True, slots=True)
class EventWorkerResult:
    """What one pass of the worker did. job is None when there was no work.

    lease_lost means the job was taken over or removed while the model ran, so
    this worker saved nothing and left the job alone.
    """

    job: EventExtractionJob | None
    event_count: int = 0
    lease_lost: bool = False


class EventExtractionWorker:
    """Takes one queued event extraction job and runs it.

    The claim is committed before the model runs, so no transaction or row lock
    stays open while the text is read, and the lease is extended meanwhile.

    Events are not matched across chunks or documents yet. Each event the model
    finds becomes its own Event, with one EventEvidence row pointing to the
    chunk. Reading a chunk again with the same model replaces those events.
    When a chunk is deleted, its evidence goes with it, but the events stay.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        extractors: EventExtractorRegistry,
        clock: Clock = utc_now,
        lease: LeasePolicy = DEFAULT_LEASE_POLICY,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.session_factory = session_factory
        self.extractors = extractors
        self.clock = clock
        self.lease = lease
        self.sleep = sleep

    async def run_once(self) -> EventWorkerResult:
        job = await self._claim()
        if job is None:
            return EventWorkerResult(job=None)
        token = job.lease_token
        # Every claim sets a token.
        assert token is not None
        chunk = await self._load_chunk(job.chunk_id)
        if chunk is None:
            # Deleting a chunk deletes its jobs, so this job is gone too.
            return EventWorkerResult(job=job, lease_lost=True)
        async with keep_lease_alive(
            lambda: self._heartbeat(job.id, token), self.lease, self.sleep
        ) as keeper:
            events, error = await self._extract(job, chunk)
        finished = None if keeper.lost else await self._finish(job, token, chunk, events, error)
        if finished is None:
            logger.warning("Event extraction job %s was taken over by another worker", job.id)
            return EventWorkerResult(job=job, lease_lost=True)
        return EventWorkerResult(job=finished, event_count=0 if error else len(events))

    async def _extract(
        self, job: EventExtractionJob, chunk: DocumentChunk
    ) -> tuple[list[ExtractedEvent], str | None]:
        """Return the checked events, or the error to store."""
        try:
            extractor = self.extractors.get(job.provider, job.model)
            return await extract_events(extractor, chunk.text), None
        except SignalScopeError as error:
            logger.warning("Event extraction job %s failed: %s", job.id, error)
            return [], str(error)
        except Exception:
            logger.exception("Event extraction job %s failed", job.id)
            return [], UNEXPECTED_EXTRACTION_ERROR

    async def _claim(self) -> EventExtractionJob | None:
        async with self.session_factory() as session:
            job = await EventExtractionJobRepository(session).claim_next(
                self.clock(), self.extractors.keys(), self.lease
            )
            await session.commit()
        return job

    async def _load_chunk(self, chunk_id: uuid.UUID) -> DocumentChunk | None:
        async with self.session_factory() as session:
            return await session.get(DocumentChunk, chunk_id)

    async def _heartbeat(self, job_id: uuid.UUID, token: uuid.UUID) -> bool:
        async with self.session_factory() as session:
            held = await EventExtractionJobRepository(session).heartbeat(
                job_id, token, self.clock(), self.lease
            )
            await session.commit()
        return held

    async def _finish(
        self,
        job: EventExtractionJob,
        token: uuid.UUID,
        chunk: DocumentChunk,
        events: list[ExtractedEvent],
        error: str | None,
    ) -> EventExtractionJob | None:
        """Save the outcome, or return None when this worker no longer holds the job."""
        async with self.session_factory() as session:
            try:
                current = await session.get(
                    EventExtractionJob, job.id, with_for_update=True, populate_existing=True
                )
                if (
                    current is None
                    or current.status is not EventExtractionJobStatus.RUNNING
                    or current.lease_token != token
                ):
                    await session.rollback()
                    return None
                jobs = EventExtractionJobRepository(session)
                if error is not None:
                    finished = await jobs.mark_failed(job.id, token, self.clock(), error)
                else:
                    await _replace_events(session, job, chunk, events)
                    finished = await jobs.mark_completed(job.id, token, self.clock())
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return finished


async def _replace_events(
    session: AsyncSession,
    job: EventExtractionJob,
    chunk: DocumentChunk,
    events: list[ExtractedEvent],
) -> None:
    # Events from this chunk and model were made by an earlier run of this job.
    # Deleting them deletes their evidence too.
    await session.execute(
        delete(Event).where(
            Event.id.in_(
                select(EventEvidence.event_id).where(
                    EventEvidence.chunk_id == chunk.id,
                    EventEvidence.provider == job.provider,
                    EventEvidence.model == job.model,
                )
            )
        )
    )
    for extracted in events:
        event = Event(
            event_type=extracted.event_type,
            title=extracted.title,
            summary=extracted.summary,
            occurred_at=extracted.occurred_at,
        )
        session.add(event)
        await session.flush()
        session.add(
            EventEvidence(
                event_id=event.id,
                chunk_id=chunk.id,
                confidence=extracted.confidence,
                provider=job.provider,
                model=job.model,
                evidence_metadata=dict(extracted.metadata),
            )
        )
    await session.flush()
