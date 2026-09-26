import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import SignalScopeError
from signalscope.core.leases import DEFAULT_LEASE_POLICY, LeasePolicy
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.entities.job import EntityExtractionJob, EntityExtractionJobStatus
from signalscope.domain.entities.job_repository import EntityExtractionJobRepository
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.entities.names import normalize_entity_name
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.entities.provider import ExtractedEntityMention, extract_mentions
from signalscope.entities.registry import EntityExtractorRegistry
from signalscope.workers.heartbeat import Sleep, keep_lease_alive

logger = logging.getLogger(__name__)

UNEXPECTED_EXTRACTION_ERROR = "Entity extraction failed with an unexpected error."


@dataclass(frozen=True, slots=True)
class EntityWorkerResult:
    """What one pass of the worker did. job is None when there was no work.

    lease_lost means the job was taken over or removed while the model ran, so
    this worker saved nothing and left the job alone.
    """

    job: EntityExtractionJob | None
    mention_count: int = 0
    lease_lost: bool = False


class EntityExtractionWorker:
    """Takes one queued entity extraction job and runs it.

    The claim is committed before the model runs, so no transaction or row lock
    stays open while the text is read, and the lease is extended meanwhile. The
    mentions replace earlier ones from the same model, together with the
    finished job, in one transaction, and only when this worker still holds the
    job.

    Mentions are linked to entities by normalized name and type. An entity is
    created the first time a name and type are seen. There is no fuzzy linking.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        extractors: EntityExtractorRegistry,
        clock: Clock = utc_now,
        lease: LeasePolicy = DEFAULT_LEASE_POLICY,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.session_factory = session_factory
        self.extractors = extractors
        self.clock = clock
        self.lease = lease
        self.sleep = sleep

    async def run_once(self) -> EntityWorkerResult:
        job = await self._claim()
        if job is None:
            return EntityWorkerResult(job=None)
        token = job.lease_token
        # Every claim sets a token.
        assert token is not None
        chunk = await self._load_chunk(job.chunk_id)
        if chunk is None:
            # Deleting a chunk deletes its jobs, so this job is gone too.
            return EntityWorkerResult(job=job, lease_lost=True)
        async with keep_lease_alive(
            lambda: self._heartbeat(job.id, token), self.lease, self.sleep
        ) as keeper:
            mentions, error = await self._extract(job, chunk)
        finished = None if keeper.lost else await self._finish(job, token, chunk, mentions, error)
        if finished is None:
            logger.warning("Entity extraction job %s was taken over by another worker", job.id)
            return EntityWorkerResult(job=job, lease_lost=True)
        return EntityWorkerResult(job=finished, mention_count=0 if error else len(mentions))

    async def _extract(
        self, job: EntityExtractionJob, chunk: DocumentChunk
    ) -> tuple[list[ExtractedEntityMention], str | None]:
        """Return the checked mentions, or the error to store."""
        try:
            extractor = self.extractors.get(job.provider, job.model)
            return await extract_mentions(extractor, chunk.text), None
        except SignalScopeError as error:
            logger.warning("Entity extraction job %s failed: %s", job.id, error)
            return [], str(error)
        except Exception:
            logger.exception("Entity extraction job %s failed", job.id)
            return [], UNEXPECTED_EXTRACTION_ERROR

    async def _claim(self) -> EntityExtractionJob | None:
        async with self.session_factory() as session:
            job = await EntityExtractionJobRepository(session).claim_next(
                self.clock(), self.extractors.keys(), self.lease
            )
            await session.commit()
        return job

    async def _load_chunk(self, chunk_id: uuid.UUID) -> DocumentChunk | None:
        async with self.session_factory() as session:
            return await session.get(DocumentChunk, chunk_id)

    async def _heartbeat(self, job_id: uuid.UUID, token: uuid.UUID) -> bool:
        async with self.session_factory() as session:
            held = await EntityExtractionJobRepository(session).heartbeat(
                job_id, token, self.clock(), self.lease
            )
            await session.commit()
        return held

    async def _finish(
        self,
        job: EntityExtractionJob,
        token: uuid.UUID,
        chunk: DocumentChunk,
        mentions: list[ExtractedEntityMention],
        error: str | None,
    ) -> EntityExtractionJob | None:
        """Save the outcome, or return None when this worker no longer holds the job."""
        async with self.session_factory() as session:
            try:
                current = await session.get(
                    EntityExtractionJob, job.id, with_for_update=True, populate_existing=True
                )
                if (
                    current is None
                    or current.status is not EntityExtractionJobStatus.RUNNING
                    or current.lease_token != token
                ):
                    await session.rollback()
                    return None
                jobs = EntityExtractionJobRepository(session)
                if error is not None:
                    finished = await jobs.mark_failed(job.id, token, self.clock(), error)
                else:
                    await _replace_mentions(session, job, chunk, mentions)
                    finished = await jobs.mark_completed(job.id, token, self.clock())
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return finished


async def _replace_mentions(
    session: AsyncSession,
    job: EntityExtractionJob,
    chunk: DocumentChunk,
    mentions: list[ExtractedEntityMention],
) -> None:
    await session.execute(
        delete(EntityMention).where(
            EntityMention.chunk_id == chunk.id,
            EntityMention.provider == job.provider,
            EntityMention.model == job.model,
        )
    )
    if not mentions:
        return
    entity_ids = await _entity_ids(session, mentions)
    session.add_all(
        EntityMention(
            entity_id=entity_ids[(normalize_entity_name(mention.text), mention.entity_type)],
            document_id=chunk.document_id,
            chunk_id=chunk.id,
            surface_text=mention.text,
            entity_type=mention.entity_type,
            start_char=mention.start_char,
            end_char=mention.end_char,
            confidence=mention.confidence,
            provider=job.provider,
            model=job.model,
            chunk_text_hash=chunk.text_hash,
            mention_metadata=dict(mention.metadata),
        )
        for mention in _one_per_place(mentions)
    )
    await session.flush()


async def _entity_ids(
    session: AsyncSession, mentions: list[ExtractedEntityMention]
) -> dict[tuple[str, str], uuid.UUID]:
    """Find or create the entity of each (normalized name, type) in mentions."""
    names: dict[tuple[str, str], str] = {}
    for mention in mentions:
        # The first surface text seen becomes the name shown for a new entity.
        names.setdefault((normalize_entity_name(mention.text), mention.entity_type), mention.text)
    await session.execute(
        insert(Entity)
        .values(
            [
                {
                    "id": uuid.uuid4(),
                    "canonical_name": text.strip(),
                    "normalized_name": normalized,
                    "entity_type": entity_type,
                }
                for (normalized, entity_type), text in names.items()
            ]
        )
        .on_conflict_do_nothing(index_elements=["normalized_name", "entity_type"])
    )
    rows = await session.execute(
        select(Entity.normalized_name, Entity.entity_type, Entity.id).where(
            tuple_(Entity.normalized_name, Entity.entity_type).in_(list(names))
        )
    )
    return {(normalized, entity_type): entity_id for normalized, entity_type, entity_id in rows}


def _one_per_place(mentions: list[ExtractedEntityMention]) -> list[ExtractedEntityMention]:
    """Keep the first mention at each place. The table allows one per place and model."""
    kept: dict[tuple[int, int], ExtractedEntityMention] = {}
    for mention in mentions:
        kept.setdefault((mention.start_char, mention.end_char), mention)
    return list(kept.values())
