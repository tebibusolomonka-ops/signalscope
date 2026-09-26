import asyncio
import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_claims import FakeClaimExtractor
from signalscope.claims.provider import ExtractedClaim, InvalidExtractedClaimError
from signalscope.claims.registry import ClaimExtractorRegistry
from signalscope.core.leases import LeasePolicy
from signalscope.domain.claims.job import ClaimExtractionJob, ClaimExtractionJobStatus
from signalscope.domain.claims.job_repository import ClaimExtractionJobRepository
from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.claims.queue import ClaimExtractionQueueService
from signalscope.domain.claims.worker import (
    UNEXPECTED_EXTRACTION_ERROR,
    ClaimExtractionWorker,
    ClaimWorkerResult,
)
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.model import Source, SourceType
from signalscope.domain.sources.scheduling import utc_now

pytestmark = pytest.mark.anyio

FAST_LEASE = LeasePolicy(timedelta(milliseconds=60))
TIMEOUT_SECONDS = 10
TEXT = "The ministry spoke. Unemployment fell to 5%. Prices rose 3% in May."


@pytest.fixture
def extractor() -> FakeClaimExtractor:
    return FakeClaimExtractor()


def worker(
    session_factory: async_sessionmaker[AsyncSession],
    extractor: FakeClaimExtractor,
    lease: LeasePolicy | None = None,
) -> ClaimExtractionWorker:
    registry = ClaimExtractorRegistry()
    registry.register(extractor)
    return ClaimExtractionWorker(session_factory, registry, lease=lease or LeasePolicy())


async def create_chunks(
    session_factory: async_sessionmaker[AsyncSession], *texts: str
) -> list[DocumentChunk]:
    chunks = [
        TextChunk(
            position=index,
            text=value,
            start_char=0,
            end_char=len(value),
            text_hash=hashlib.sha256(value.encode()).hexdigest(),
        )
        for index, value in enumerate(texts)
    ]
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id)
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunks)
        await session.commit()
        saved = await repository.list_by_document(document.id)
    await ClaimExtractionQueueService(session_factory).queue_chunks(
        [chunk.id for chunk in saved], "test", "number-sentences"
    )
    return saved


async def claims(session_factory: async_sessionmaker[AsyncSession]) -> list[Claim]:
    async with session_factory() as session:
        return list(
            await session.scalars(select(Claim).order_by(Claim.normalized_text, Claim.claim_type))
        )


async def evidence(session_factory: async_sessionmaker[AsyncSession]) -> list[ClaimEvidence]:
    async with session_factory() as session:
        return list(
            await session.scalars(
                select(ClaimEvidence).order_by(ClaimEvidence.chunk_id, ClaimEvidence.start_char)
            )
        )


async def only_job(session_factory: async_sessionmaker[AsyncSession]) -> ClaimExtractionJob:
    async with session_factory() as session:
        [job] = await session.scalars(select(ClaimExtractionJob))
    return job


async def test_no_job(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeClaimExtractor
) -> None:
    assert await worker(session_factory, extractor).run_once() == ClaimWorkerResult(job=None)


async def test_one_claim(session_factory: async_sessionmaker[AsyncSession]) -> None:
    extractor = FakeClaimExtractor()
    extractor.answer = [
        ExtractedClaim(
            text="Unemployment fell to 5%",
            claim_type="Statistic",
            surface_text="Unemployment fell to 5%",
            start_char=20,
            end_char=43,
            confidence=0.9,
            metadata={"sentence": 1},
        )
    ]
    [chunk] = await create_chunks(session_factory, TEXT)

    result = await worker(session_factory, extractor).run_once()

    assert result.job is not None and result.job.status is ClaimExtractionJobStatus.COMPLETED
    assert result.claim_count == 1
    [claim] = await claims(session_factory)
    assert (claim.text, claim.normalized_text, claim.claim_type) == (
        "Unemployment fell to 5%",
        "unemployment fell to 5%",
        "statistic",
    )
    [row] = await evidence(session_factory)
    assert (row.claim_id, row.chunk_id, row.confidence) == (claim.id, chunk.id, 0.9)
    assert TEXT[row.start_char : row.end_char] == row.surface_text == "Unemployment fell to 5%"
    assert (row.provider, row.model, row.evidence_metadata) == (
        "test",
        "number-sentences",
        {"sentence": 1},
    )


async def test_several_claims(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeClaimExtractor
) -> None:
    await create_chunks(session_factory, TEXT)

    result = await worker(session_factory, extractor).run_once()

    assert result.claim_count == 2
    assert [claim.normalized_text for claim in await claims(session_factory)] == [
        "prices rose 3% in may",
        "unemployment fell to 5%",
    ]


async def test_the_same_claim_is_reused(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeClaimExtractor
) -> None:
    await create_chunks(session_factory, "Unemployment fell to 5%.", "UNEMPLOYMENT  fell to 5%.")
    claim_worker = worker(session_factory, extractor)

    await claim_worker.run_once()
    await claim_worker.run_once()

    [claim] = await claims(session_factory)
    assert {row.claim_id for row in await evidence(session_factory)} == {claim.id}
    assert len(await evidence(session_factory)) == 2


async def test_another_type_is_another_claim(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    extractor = FakeClaimExtractor()
    extractor.answer = [
        ExtractedClaim("Prices rose 3%", "statistic", "Prices rose 3% in May", 45, 66),
        ExtractedClaim("Prices rose 3%", "quote", "Unemployment fell to 5%", 20, 43),
    ]
    await create_chunks(session_factory, TEXT)

    await worker(session_factory, extractor).run_once()

    assert {
        (claim.normalized_text, claim.claim_type) for claim in await claims(session_factory)
    } == {
        ("prices rose 3%", "statistic"),
        ("prices rose 3%", "quote"),
    }


async def test_reading_again_replaces_the_evidence(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeClaimExtractor
) -> None:
    await create_chunks(session_factory, TEXT)
    await worker(session_factory, extractor).run_once()
    first = {row.id for row in await evidence(session_factory)}
    async with session_factory() as session:
        job = await session.scalar(select(ClaimExtractionJob))
        assert job is not None
        job.status = ClaimExtractionJobStatus.PENDING
        await session.commit()

    await worker(session_factory, extractor).run_once()

    again = await evidence(session_factory)
    assert len(again) == 2
    assert first.isdisjoint(row.id for row in again)
    # The claims themselves are reused, not made again.
    assert len(await claims(session_factory)) == 2


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (InvalidExtractedClaimError("Model is not ready."), "Model is not ready."),
        (RuntimeError("Traceback with private details"), UNEXPECTED_EXTRACTION_ERROR),
    ],
    ids=["expected error", "unexpected error"],
)
async def test_model_error_fails_the_job_with_a_safe_message(
    session_factory: async_sessionmaker[AsyncSession],
    extractor: FakeClaimExtractor,
    error: Exception,
    message: str,
) -> None:
    await create_chunks(session_factory, TEXT)
    extractor.error = error

    result = await worker(session_factory, extractor).run_once()

    assert result.job is not None
    assert (result.job.status, result.job.last_error) == (ClaimExtractionJobStatus.FAILED, message)
    assert await claims(session_factory) == []


async def test_lease_is_extended_and_no_transaction_is_held(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeClaimExtractor
) -> None:
    await create_chunks(session_factory, TEXT)
    extractor.gate = asyncio.Event()
    run = asyncio.create_task(worker(session_factory, extractor, FAST_LEASE).run_once())
    await asyncio.wait_for(extractor.started.wait(), TIMEOUT_SECONDS)
    claimed = await only_job(session_factory)

    # NOWAIT fails at once if another transaction still locks the claimed row.
    async with session_factory() as session:
        locked = list(
            await session.scalars(select(ClaimExtractionJob.id).with_for_update(nowait=True))
        )
        await session.rollback()
    async with asyncio.timeout(TIMEOUT_SECONDS):
        while (await only_job(session_factory)).heartbeat_at == claimed.heartbeat_at:
            await asyncio.sleep(0.01)
    extractor.gate.set()
    result = await asyncio.wait_for(run, TIMEOUT_SECONDS)

    assert len(locked) == 1
    assert result.job is not None and result.job.status is ClaimExtractionJobStatus.COMPLETED


async def test_job_taken_over_is_left_alone(
    session_factory: async_sessionmaker[AsyncSession], extractor: FakeClaimExtractor
) -> None:
    await create_chunks(session_factory, TEXT)
    extractor.gate = asyncio.Event()
    # The default lease is long, so no heartbeat notices the takeover first.
    run = asyncio.create_task(worker(session_factory, extractor).run_once())
    await asyncio.wait_for(extractor.started.wait(), TIMEOUT_SECONDS)

    later = utc_now() + timedelta(hours=1)
    async with session_factory() as session:
        repository = ClaimExtractionJobRepository(session)
        await repository.recover_stale(later, 10)
        other = await repository.claim_next(later, [("test", "number-sentences")])
        await session.commit()
    assert other is not None
    extractor.gate.set()
    result = await asyncio.wait_for(run, TIMEOUT_SECONDS)

    assert result.lease_lost is True
    job = await only_job(session_factory)
    assert (job.status, job.lease_token) == (ClaimExtractionJobStatus.RUNNING, other.lease_token)
    assert await claims(session_factory) == []
