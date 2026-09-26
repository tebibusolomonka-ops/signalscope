import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import SignalScopeError
from signalscope.core.leases import DEFAULT_LEASE_POLICY, LeasePolicy
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.domain.search.embedding_job_repository import EmbeddingJobRepository
from signalscope.domain.search.embedding_repository import ChunkEmbeddingRepository
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.embeddings.provider import EmbeddingInputRole, embed
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.workers.heartbeat import Sleep, keep_lease_alive

logger = logging.getLogger(__name__)

UNEXPECTED_EMBEDDING_ERROR = "Embedding failed with an unexpected error."


@dataclass(frozen=True, slots=True)
class EmbeddingWorkerResult:
    """What one pass of the worker did. job is None when there was no work.

    lease_lost means the job was taken over or removed while this worker was
    embedding, so this worker saved nothing and left the job alone.
    """

    job: EmbeddingJob | None
    lease_lost: bool = False


@dataclass(frozen=True, slots=True)
class _Outcome:
    vector: list[float] | None = None
    error: str | None = None


class EmbeddingWorker:
    """Takes one queued embedding job and runs it.

    Only jobs for models in the registry are claimed. The claim is committed
    before the model runs, so no transaction or row lock stays open while the
    text is embedded. The lease is extended in the background meanwhile. The
    vector and the finished job are saved together in one transaction, and only
    when this worker still holds the job.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        providers: EmbeddingProviderRegistry,
        clock: Clock = utc_now,
        lease: LeasePolicy = DEFAULT_LEASE_POLICY,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.session_factory = session_factory
        self.providers = providers
        self.clock = clock
        self.lease = lease
        self.sleep = sleep

    async def run_once(self) -> EmbeddingWorkerResult:
        job = await self._claim()
        if job is None:
            return EmbeddingWorkerResult(job=None)
        chunk = await self._load_chunk(job.chunk_id)
        if chunk is None:
            # Deleting a chunk deletes its jobs, so this job is gone too.
            return EmbeddingWorkerResult(job=job, lease_lost=True)
        token = job.lease_token
        # Every claim sets a token.
        assert token is not None
        async with keep_lease_alive(
            lambda: self._heartbeat(job.id, token), self.lease, self.sleep
        ) as keeper:
            outcome = await self._embed(job, chunk)
        if keeper.lost:
            logger.warning("Embedding job %s was taken over by another worker", job.id)
            return EmbeddingWorkerResult(job=job, lease_lost=True)
        finished = await self._finish(job, token, chunk, outcome)
        if finished is None:
            logger.warning("Embedding job %s was taken over by another worker", job.id)
            return EmbeddingWorkerResult(job=job, lease_lost=True)
        return EmbeddingWorkerResult(job=finished)

    async def _embed(self, job: EmbeddingJob, chunk: DocumentChunk) -> _Outcome:
        """Return the new vector, the error to store, or neither when the vector is current."""
        if await self._has_current_embedding(job, chunk):
            return _Outcome()
        try:
            provider = self.providers.get(job.provider, job.model)
            [vector] = await embed(provider, [chunk.text], EmbeddingInputRole.PASSAGE)
        except SignalScopeError as error:
            # These messages are written for people, such as "Model is not ready."
            logger.warning("Embedding job %s failed: %s", job.id, error)
            return _Outcome(error=str(error))
        except Exception:
            logger.exception("Embedding job %s failed", job.id)
            return _Outcome(error=UNEXPECTED_EMBEDDING_ERROR)
        return _Outcome(vector=vector)

    async def _claim(self) -> EmbeddingJob | None:
        async with self.session_factory() as session:
            job = await EmbeddingJobRepository(session).claim_next(
                self.clock(), self.providers.keys(), self.lease
            )
            await session.commit()
        return job

    async def _load_chunk(self, chunk_id: uuid.UUID) -> DocumentChunk | None:
        async with self.session_factory() as session:
            return await session.get(DocumentChunk, chunk_id)

    async def _has_current_embedding(self, job: EmbeddingJob, chunk: DocumentChunk) -> bool:
        async with self.session_factory() as session:
            embedding = await ChunkEmbeddingRepository(session).get(
                chunk.id, job.provider, job.model
            )
        return embedding is not None and embedding.chunk_text_hash == chunk.text_hash

    async def _heartbeat(self, job_id: uuid.UUID, token: uuid.UUID) -> bool:
        async with self.session_factory() as session:
            held = await EmbeddingJobRepository(session).heartbeat(
                job_id, token, self.clock(), self.lease
            )
            await session.commit()
        return held

    async def _finish(
        self, job: EmbeddingJob, token: uuid.UUID, chunk: DocumentChunk, outcome: _Outcome
    ) -> EmbeddingJob | None:
        """Save the outcome, or return None when this worker no longer holds the job."""
        async with self.session_factory() as session:
            try:
                current = await session.get(
                    EmbeddingJob, job.id, with_for_update=True, populate_existing=True
                )
                # A job recovered, and maybe claimed again, has another token.
                if (
                    current is None
                    or current.status is not EmbeddingJobStatus.RUNNING
                    or current.lease_token != token
                ):
                    await session.rollback()
                    return None
                jobs = EmbeddingJobRepository(session)
                if outcome.error is not None:
                    finished = await jobs.mark_failed(job.id, token, self.clock(), outcome.error)
                else:
                    if outcome.vector is not None:
                        await ChunkEmbeddingRepository(session).save(
                            chunk.id, job.provider, job.model, chunk.text_hash, outcome.vector
                        )
                    finished = await jobs.mark_completed(job.id, token, self.clock())
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return finished
