import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import SignalScopeError
from signalscope.core.leases import DEFAULT_LEASE_POLICY, LeasePolicy
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.domain.search.embedding_job_repository import EmbeddingJobRepository
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.search.embedding_repository import ChunkEmbeddingRepository
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.embeddings.provider import EmbeddingInputRole, embed
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.workers.heartbeat import Sleep, keep_lease_alive

logger = logging.getLogger(__name__)

UNEXPECTED_EMBEDDING_ERROR = "Embedding failed with an unexpected error."
DEFAULT_WORKER_BATCH_SIZE = 32


@dataclass(frozen=True, slots=True)
class EmbeddingWorkerResult:
    """What one pass of the worker did. jobs is empty when there was no work.

    jobs holds every claimed job, as this worker left it. lease_lost counts
    jobs that were taken over or removed while the model ran. This worker
    saved nothing for them and left them alone.
    """

    jobs: tuple[EmbeddingJob, ...] = ()
    completed: int = 0
    failed: int = 0
    lease_lost: int = 0


@dataclass(frozen=True, slots=True)
class _Work:
    job: EmbeddingJob
    token: uuid.UUID
    chunk: DocumentChunk


class EmbeddingWorker:
    """Claims a batch of embedding jobs for one model and runs them together.

    Only models in the registry are claimed. The claim is committed before the
    model runs, so no transaction or row lock stays open while the texts are
    embedded, and the leases of the batch are extended meanwhile. All texts go
    to the model in one call. The vectors and finished jobs are then saved in
    one transaction, but only for the jobs this worker still holds.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        providers: EmbeddingProviderRegistry,
        clock: Clock = utc_now,
        lease: LeasePolicy = DEFAULT_LEASE_POLICY,
        sleep: Sleep = asyncio.sleep,
        batch_size: int = DEFAULT_WORKER_BATCH_SIZE,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self.session_factory = session_factory
        self.providers = providers
        self.clock = clock
        self.lease = lease
        self.sleep = sleep
        self.batch_size = batch_size

    async def run_once(self) -> EmbeddingWorkerResult:
        jobs = await self._claim()
        if not jobs:
            return EmbeddingWorkerResult()
        work, current = await self._load(jobs)
        # Deleting a chunk deletes its job, so a missing chunk means a lost job.
        gone = len(jobs) - len(work)
        needed = [item for item in work if item.chunk.id not in current]
        held = {item.job.id: item.token for item in work}
        vectors: list[list[float]] = []
        error: str | None = None
        async with keep_lease_alive(
            lambda: self._heartbeat(held), self.lease, self.sleep
        ) as keeper:
            if needed:
                vectors, error = await self._embed(needed)
        if keeper.lost:
            logger.warning("All %s embedding jobs were taken over by other workers", len(jobs))
            return EmbeddingWorkerResult(jobs=tuple(jobs), lease_lost=len(jobs))
        new_vectors = {item.job.id: vector for item, vector in zip(needed, vectors, strict=False)}
        needed_ids = {item.job.id for item in needed}
        finished, lost = await self._finish(work, needed_ids, new_vectors, error)
        failed = sum(job.status is EmbeddingJobStatus.FAILED for job in finished)
        if lost:
            logger.warning("%s embedding jobs were taken over by other workers", lost)
        by_id = {job.id: job for job in finished}
        return EmbeddingWorkerResult(
            jobs=tuple(by_id.get(job.id, job) for job in jobs),
            completed=len(finished) - failed,
            failed=failed,
            lease_lost=lost + gone,
        )

    async def _claim(self) -> list[EmbeddingJob]:
        """Claim jobs of the first registered model that has any waiting."""
        models = self.providers.keys()
        for provider_name, model_name in models:
            async with self.session_factory() as session:
                jobs = await EmbeddingJobRepository(session).claim_batch(
                    self.clock(), provider_name, model_name, self.batch_size, self.lease
                )
                await session.commit()
            if jobs:
                return jobs
        return []

    async def _load(self, jobs: list[EmbeddingJob]) -> tuple[list[_Work], set[uuid.UUID]]:
        """Return the jobs with their chunks, and the chunks whose embedding is current."""
        provider_name, model_name = jobs[0].provider, jobs[0].model
        chunk_ids = [job.chunk_id for job in jobs]
        async with self.session_factory() as session:
            chunks = {
                chunk.id: chunk
                for chunk in await session.scalars(
                    select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))
                )
            }
            current = set(
                await session.scalars(
                    select(ChunkEmbedding.chunk_id)
                    .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
                    .where(
                        ChunkEmbedding.chunk_id.in_(chunk_ids),
                        ChunkEmbedding.provider == provider_name,
                        ChunkEmbedding.model == model_name,
                        ChunkEmbedding.chunk_text_hash == DocumentChunk.text_hash,
                    )
                )
            )
        work = []
        for job in jobs:
            chunk = chunks.get(job.chunk_id)
            # Every claim sets a token.
            assert job.lease_token is not None
            if chunk is not None:
                work.append(_Work(job, job.lease_token, chunk))
        return work, current

    async def _embed(self, needed: list[_Work]) -> tuple[list[list[float]], str | None]:
        """Embed the chunk texts in one call. Returns the vectors, or the error to store."""
        first = needed[0].job
        try:
            provider = self.providers.get(first.provider, first.model)
            vectors = await embed(
                provider, [item.chunk.text for item in needed], EmbeddingInputRole.PASSAGE
            )
        except SignalScopeError as error:
            # These messages are written for people, such as "Model is not ready."
            logger.warning("Embedding batch of %s jobs failed: %s", len(needed), error)
            return [], str(error)
        except Exception:
            logger.exception("Embedding batch of %s jobs failed", len(needed))
            return [], UNEXPECTED_EMBEDDING_ERROR
        return vectors, None

    async def _heartbeat(self, held: dict[uuid.UUID, uuid.UUID]) -> bool:
        """Extend the lease of every job still held. False once none is held."""
        async with self.session_factory() as session:
            repository = EmbeddingJobRepository(session)
            for job_id, token in list(held.items()):
                if not await repository.heartbeat(job_id, token, self.clock(), self.lease):
                    del held[job_id]
            await session.commit()
        return bool(held)

    async def _finish(
        self,
        work: list[_Work],
        needed_ids: set[uuid.UUID],
        vectors: dict[uuid.UUID, list[float]],
        error: str | None,
    ) -> tuple[list[EmbeddingJob], int]:
        """Save the results of the jobs still held. Returns them and the number lost.

        Jobs in needed_ids get their new vector, or fail with error. The others
        already had a current embedding and simply complete.
        """
        async with self.session_factory() as session:
            try:
                owned = {
                    job.id: job.lease_token
                    for job in await session.scalars(
                        select(EmbeddingJob)
                        .where(
                            EmbeddingJob.id.in_([item.job.id for item in work]),
                            EmbeddingJob.status == EmbeddingJobStatus.RUNNING,
                        )
                        .order_by(EmbeddingJob.id)
                        .with_for_update()
                    )
                }
                jobs = EmbeddingJobRepository(session)
                embeddings = ChunkEmbeddingRepository(session)
                finished = []
                for item in work:
                    # A job recovered, and maybe claimed again, has another token.
                    if owned.get(item.job.id) != item.token:
                        continue
                    vector = vectors.get(item.job.id)
                    if item.job.id in needed_ids and vector is None:
                        message = error or UNEXPECTED_EMBEDDING_ERROR
                        finished.append(
                            await jobs.mark_failed(item.job.id, item.token, self.clock(), message)
                        )
                        continue
                    if vector is not None:
                        job = item.job
                        await embeddings.save(
                            item.chunk.id, job.provider, job.model, item.chunk.text_hash, vector
                        )
                    finished.append(
                        await jobs.mark_completed(item.job.id, item.token, self.clock())
                    )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return finished, len(work) - len(finished)
