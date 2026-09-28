import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import SignalScopeError
from signalscope.core.leases import DEFAULT_LEASE_POLICY, LeasePolicy
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.events.job import EventExtractionJob, EventExtractionJobStatus
from signalscope.domain.events.job_repository import EventExtractionJobRepository
from signalscope.domain.events.linking import EventLinkingService
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.events.repository import EventRepository
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
    # New events put in a cluster after the job was saved.
    linked_count: int = 0


class EventExtractionWorker:
    """Takes one queued event extraction job and runs it.

    The claim is committed before the model runs, so no transaction or row lock
    stays open while the text is read, and the lease is extended meanwhile.

    Events are not matched across chunks or documents yet. Each event the model
    finds becomes its own Event, with one EventEvidence row pointing to the
    chunk. Reading a chunk again with the same model replaces that evidence,
    and events left with no evidence at all are deleted.

    After the job is saved, the new events are linked into event clusters. A
    linking failure is only logged: the events stay saved but unclustered, and
    the link-events command can link them later.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        extractors: EventExtractorRegistry,
        clock: Clock = utc_now,
        lease: LeasePolicy = DEFAULT_LEASE_POLICY,
        sleep: Sleep = asyncio.sleep,
        linker: EventLinkingService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.extractors = extractors
        self.linker = EventLinkingService(session_factory) if linker is None else linker
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
        saved = None if keeper.lost else await self._finish(job, token, chunk, events, error)
        if saved is None:
            logger.warning("Event extraction job %s was taken over by another worker", job.id)
            return EventWorkerResult(job=job, lease_lost=True)
        finished, created = saved
        # The job and its events are committed. Linking runs after, outside the model call.
        linked = await self._link(created)
        return EventWorkerResult(
            job=finished, event_count=0 if error else len(events), linked_count=linked
        )

    async def _link(self, event_ids: list[uuid.UUID]) -> int:
        linked = 0
        for event_id in event_ids:
            try:
                if await self.linker.link_event(event_id) is not None:
                    linked += 1
            except Exception:
                logger.exception("Linking event %s failed; it stays unclustered", event_id)
        return linked

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
    ) -> tuple[EventExtractionJob, list[uuid.UUID]] | None:
        """Save the outcome and return the job and the new event IDs.

        Returns None when this worker no longer holds the job.
        """
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
                created: list[uuid.UUID] = []
                if error is not None:
                    finished = await jobs.mark_failed(job.id, token, self.clock(), error)
                else:
                    created = await _replace_events(session, job, chunk, events)
                    finished = await jobs.mark_completed(job.id, token, self.clock())
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return finished, created


async def _replace_events(
    session: AsyncSession,
    job: EventExtractionJob,
    chunk: DocumentChunk,
    events: list[ExtractedEvent],
) -> list[uuid.UUID]:
    """Replace this chunk's events from the job's model and return the new event IDs."""
    # Evidence from this chunk and model was made by an earlier run of this job.
    # Its events are deleted only when no other evidence points to them.
    replaced = await session.scalars(
        delete(EventEvidence)
        .where(
            EventEvidence.chunk_id == chunk.id,
            EventEvidence.provider == job.provider,
            EventEvidence.model == job.model,
        )
        .returning(EventEvidence.event_id)
    )
    await EventRepository(session).delete_orphaned_events(set(replaced.all()))
    created = []
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
        created.append(event.id)
    await session.flush()
    return created
