import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.claims.provider import ExtractedClaim, extract_claims
from signalscope.claims.registry import ClaimExtractorRegistry
from signalscope.core.errors import SignalScopeError
from signalscope.core.leases import DEFAULT_LEASE_POLICY, LeasePolicy
from signalscope.domain.claims.job import ClaimExtractionJob, ClaimExtractionJobStatus
from signalscope.domain.claims.job_repository import ClaimExtractionJobRepository
from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.claims.text import normalize_claim_text
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.workers.heartbeat import Sleep, keep_lease_alive

logger = logging.getLogger(__name__)

UNEXPECTED_EXTRACTION_ERROR = "Claim extraction failed with an unexpected error."


@dataclass(frozen=True, slots=True)
class ClaimWorkerResult:
    """What one pass of the worker did. job is None when there was no work.

    lease_lost means the job was taken over or removed while the model ran, so
    this worker saved nothing and left the job alone.
    """

    job: ClaimExtractionJob | None
    claim_count: int = 0
    lease_lost: bool = False


class ClaimExtractionWorker:
    """Takes one queued claim extraction job and runs it.

    The job claim is committed before the model runs, so no transaction or row
    lock stays open while the text is read, and the lease is extended meanwhile.
    The evidence replaces earlier evidence from the same model, together with
    the finished job, in one transaction, and only when this worker still holds
    the job.

    Evidence is linked to claims by normalized text and type. A claim is
    created the first time a text and type are seen. Claims that say the same
    thing in other words stay separate.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        extractors: ClaimExtractorRegistry,
        clock: Clock = utc_now,
        lease: LeasePolicy = DEFAULT_LEASE_POLICY,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.session_factory = session_factory
        self.extractors = extractors
        self.clock = clock
        self.lease = lease
        self.sleep = sleep

    async def run_once(self) -> ClaimWorkerResult:
        job = await self._claim()
        if job is None:
            return ClaimWorkerResult(job=None)
        token = job.lease_token
        # Every claim sets a token.
        assert token is not None
        chunk = await self._load_chunk(job.chunk_id)
        if chunk is None:
            # Deleting a chunk deletes its jobs, so this job is gone too.
            return ClaimWorkerResult(job=job, lease_lost=True)
        async with keep_lease_alive(
            lambda: self._heartbeat(job.id, token), self.lease, self.sleep
        ) as keeper:
            claims, error = await self._extract(job, chunk)
        finished = None if keeper.lost else await self._finish(job, token, chunk, claims, error)
        if finished is None:
            logger.warning("Claim extraction job %s was taken over by another worker", job.id)
            return ClaimWorkerResult(job=job, lease_lost=True)
        return ClaimWorkerResult(job=finished, claim_count=0 if error else len(claims))

    async def _extract(
        self, job: ClaimExtractionJob, chunk: DocumentChunk
    ) -> tuple[list[ExtractedClaim], str | None]:
        """Return the checked claims, or the error to store."""
        try:
            extractor = self.extractors.get(job.provider, job.model)
            return await extract_claims(extractor, chunk.text), None
        except SignalScopeError as error:
            logger.warning("Claim extraction job %s failed: %s", job.id, error)
            return [], str(error)
        except Exception:
            logger.exception("Claim extraction job %s failed", job.id)
            return [], UNEXPECTED_EXTRACTION_ERROR

    async def _claim(self) -> ClaimExtractionJob | None:
        async with self.session_factory() as session:
            job = await ClaimExtractionJobRepository(session).claim_next(
                self.clock(), self.extractors.keys(), self.lease
            )
            await session.commit()
        return job

    async def _load_chunk(self, chunk_id: uuid.UUID) -> DocumentChunk | None:
        async with self.session_factory() as session:
            return await session.get(DocumentChunk, chunk_id)

    async def _heartbeat(self, job_id: uuid.UUID, token: uuid.UUID) -> bool:
        async with self.session_factory() as session:
            held = await ClaimExtractionJobRepository(session).heartbeat(
                job_id, token, self.clock(), self.lease
            )
            await session.commit()
        return held

    async def _finish(
        self,
        job: ClaimExtractionJob,
        token: uuid.UUID,
        chunk: DocumentChunk,
        claims: list[ExtractedClaim],
        error: str | None,
    ) -> ClaimExtractionJob | None:
        """Save the outcome, or return None when this worker no longer holds the job."""
        async with self.session_factory() as session:
            try:
                current = await session.get(
                    ClaimExtractionJob, job.id, with_for_update=True, populate_existing=True
                )
                if (
                    current is None
                    or current.status is not ClaimExtractionJobStatus.RUNNING
                    or current.lease_token != token
                ):
                    await session.rollback()
                    return None
                jobs = ClaimExtractionJobRepository(session)
                if error is not None:
                    finished = await jobs.mark_failed(job.id, token, self.clock(), error)
                else:
                    await _replace_evidence(session, job, chunk, claims)
                    finished = await jobs.mark_completed(job.id, token, self.clock())
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return finished


async def _replace_evidence(
    session: AsyncSession,
    job: ClaimExtractionJob,
    chunk: DocumentChunk,
    claims: list[ExtractedClaim],
) -> None:
    await session.execute(
        delete(ClaimEvidence).where(
            ClaimEvidence.chunk_id == chunk.id,
            ClaimEvidence.provider == job.provider,
            ClaimEvidence.model == job.model,
        )
    )
    if not claims:
        return
    claim_ids = await _claim_ids(session, claims)
    session.add_all(
        ClaimEvidence(
            claim_id=claim_ids[(normalize_claim_text(claim.text), claim.claim_type)],
            chunk_id=chunk.id,
            surface_text=claim.surface_text,
            start_char=claim.start_char,
            end_char=claim.end_char,
            confidence=claim.confidence,
            provider=job.provider,
            model=job.model,
            evidence_metadata=dict(claim.metadata),
        )
        for claim in _one_per_place(claims)
    )
    await session.flush()


async def _claim_ids(
    session: AsyncSession, claims: list[ExtractedClaim]
) -> dict[tuple[str, str], uuid.UUID]:
    """Find or create the claim of each (normalized text, type)."""
    texts: dict[tuple[str, str], str] = {}
    for claim in claims:
        # The first wording seen becomes the text shown for a new claim.
        texts.setdefault((normalize_claim_text(claim.text), claim.claim_type), claim.text)
    await session.execute(
        insert(Claim)
        .values(
            [
                {
                    "id": uuid.uuid4(),
                    "text": text,
                    "normalized_text": normalized,
                    "claim_type": claim_type,
                }
                for (normalized, claim_type), text in texts.items()
            ]
        )
        .on_conflict_do_nothing(index_elements=["normalized_text", "claim_type"])
    )
    rows = await session.execute(
        select(Claim.normalized_text, Claim.claim_type, Claim.id).where(
            tuple_(Claim.normalized_text, Claim.claim_type).in_(list(texts))
        )
    )
    return {(normalized, claim_type): claim_id for normalized, claim_type, claim_id in rows}


def _one_per_place(claims: list[ExtractedClaim]) -> list[ExtractedClaim]:
    """Keep the first claim at each place. The table allows one per place and model."""
    kept: dict[tuple[int, int], ExtractedClaim] = {}
    for claim in claims:
        kept.setdefault((claim.start_char, claim.end_char), claim)
    return list(kept.values())
