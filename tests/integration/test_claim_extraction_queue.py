import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.leases import JobNotHeldError
from signalscope.domain.claims.job import ClaimExtractionJob, ClaimExtractionJobStatus
from signalscope.domain.claims.job_repository import ClaimExtractionJobRepository
from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.claims.queue import ClaimExtractionQueueService, ClaimQueueResult
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
MODEL = ("test", "claims-1")


async def create_chunks(
    session_factory: async_sessionmaker[AsyncSession], count: int
) -> list[DocumentChunk]:
    texts = [f"The river flooded, part {index} of {uuid.uuid4()}." for index in range(count)]
    chunks = [
        TextChunk(
            position=index,
            text=text,
            start_char=0,
            end_char=len(text),
            text_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
        for index, text in enumerate(texts)
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
        return await repository.list_by_document(document.id)


async def add_evidence(
    session_factory: async_sessionmaker[AsyncSession], chunk: DocumentChunk
) -> None:
    async with session_factory() as session:
        claim = Claim(
            text="River flooded",
            normalized_text=f"river flooded {chunk.id}",
            claim_type="statistic",
        )
        session.add(claim)
        await session.flush()
        session.add(
            ClaimEvidence(
                claim_id=claim.id,
                chunk_id=chunk.id,
                surface_text="The river",
                start_char=0,
                end_char=9,
                provider=MODEL[0],
                model=MODEL[1],
            )
        )
        await session.commit()


async def add_job(
    session_factory: async_sessionmaker[AsyncSession],
    chunk: DocumentChunk,
    status: ClaimExtractionJobStatus,
) -> None:
    async with session_factory() as session:
        session.add(
            ClaimExtractionJob(chunk_id=chunk.id, provider=MODEL[0], model=MODEL[1], status=status)
        )
        await session.commit()


async def jobs(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[uuid.UUID, ClaimExtractionJob]:
    async with session_factory() as session:
        return {job.chunk_id: job for job in await session.scalars(select(ClaimExtractionJob))}


def service(session_factory: async_sessionmaker[AsyncSession]) -> ClaimExtractionQueueService:
    return ClaimExtractionQueueService(session_factory, clock=lambda: NOW)


async def test_new_chunks_get_jobs(session_factory: async_sessionmaker[AsyncSession]) -> None:
    chunks = await create_chunks(session_factory, 3)

    result = await service(session_factory).queue_chunks([chunk.id for chunk in chunks], *MODEL)

    assert result == ClaimQueueResult(chunks_seen=3, jobs_created=3)
    assert {job.status for job in (await jobs(session_factory)).values()} == {
        ClaimExtractionJobStatus.PENDING
    }


async def test_done_chunks_are_skipped(session_factory: async_sessionmaker[AsyncSession]) -> None:
    with_evidence, completed_without_claims, failed = await create_chunks(session_factory, 3)
    await add_evidence(session_factory, with_evidence)
    await add_job(session_factory, completed_without_claims, ClaimExtractionJobStatus.COMPLETED)
    await add_job(session_factory, failed, ClaimExtractionJobStatus.FAILED)

    result = await service(session_factory).queue_chunks(
        [with_evidence.id, completed_without_claims.id, failed.id], *MODEL
    )

    assert result == ClaimQueueResult(chunks_seen=3, jobs_created=1, already_extracted=2)
    saved = await jobs(session_factory)
    assert saved[failed.id].status is ClaimExtractionJobStatus.PENDING
    assert with_evidence.id not in saved


@pytest.mark.parametrize(
    "status", [ClaimExtractionJobStatus.PENDING, ClaimExtractionJobStatus.RUNNING]
)
async def test_active_job_is_not_duplicated(
    session_factory: async_sessionmaker[AsyncSession], status: ClaimExtractionJobStatus
) -> None:
    [chunk] = await create_chunks(session_factory, 1)
    await add_job(session_factory, chunk, status)

    result = await service(session_factory).queue_chunks([chunk.id], *MODEL)

    assert result == ClaimQueueResult(chunks_seen=1, already_queued=1)


async def test_backlog_is_bounded_and_moves_on(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunks = await create_chunks(session_factory, 5)

    first = await service(session_factory).queue_backlog(*MODEL, limit=2, page_size=2)
    second = await service(session_factory).queue_backlog(*MODEL, page_size=2)

    assert first == ClaimQueueResult(chunks_seen=2, jobs_created=2)
    assert second == ClaimQueueResult(chunks_seen=5, jobs_created=3, already_queued=2)
    assert set(await jobs(session_factory)) == {chunk.id for chunk in chunks}


async def queued(session_factory: async_sessionmaker[AsyncSession], count: int) -> None:
    chunks = await create_chunks(session_factory, count)
    await ClaimExtractionQueueService(
        session_factory, clock=lambda: NOW - timedelta(minutes=1)
    ).queue_chunks([chunk.id for chunk in chunks], *MODEL)


async def claim(
    session_factory: async_sessionmaker[AsyncSession], now: datetime = NOW
) -> ClaimExtractionJob | None:
    async with session_factory() as session:
        job = await ClaimExtractionJobRepository(session).claim_next(now, [MODEL])
        await session.commit()
    return job


async def test_claim_heartbeat_and_complete(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await queued(session_factory, 1)

    job = await claim(session_factory)

    assert job is not None and job.lease_token is not None
    assert (job.status, job.attempt_count) == (ClaimExtractionJobStatus.RUNNING, 1)
    async with session_factory() as session:
        repository = ClaimExtractionJobRepository(session)
        assert await repository.heartbeat(job.id, uuid.uuid4(), NOW) is False
        assert await repository.heartbeat(job.id, job.lease_token, NOW + timedelta(minutes=1))
        finished = await repository.mark_completed(job.id, job.lease_token, NOW)
        await session.commit()
    assert (finished.status, finished.lease_token) == (ClaimExtractionJobStatus.COMPLETED, None)


async def test_recovery_and_takeover(session_factory: async_sessionmaker[AsyncSession]) -> None:
    await queued(session_factory, 1)
    old = await claim(session_factory)
    assert old is not None and old.lease_token is not None

    async with session_factory() as session:
        [recovered] = await ClaimExtractionJobRepository(session).recover_stale(LATER, 10)
        await session.commit()
    assert recovered.lease_token is None
    new = await claim(session_factory, LATER)
    assert new is not None and new.lease_token != old.lease_token

    async with session_factory() as session:
        with pytest.raises(JobNotHeldError):
            await ClaimExtractionJobRepository(session).mark_completed(
                old.id, old.lease_token, LATER
            )


async def test_workers_claiming_at_the_same_time_get_different_jobs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await queued(session_factory, 3)

    claimed = await asyncio.gather(*(claim(session_factory) for _ in range(5)))

    ids = [job.id for job in claimed if job is not None]
    assert len(ids) == len(set(ids)) == 3
