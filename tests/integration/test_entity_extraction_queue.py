import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.leases import JobNotHeldError
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.job import EntityExtractionJob, EntityExtractionJobStatus
from signalscope.domain.entities.job_repository import EntityExtractionJobRepository
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.entities.queue import EntityExtractionQueueService, EntityQueueResult
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
MODEL = ("test", "ner-1")


async def create_chunks(
    session_factory: async_sessionmaker[AsyncSession], count: int
) -> list[DocumentChunk]:
    texts = [f"Merkel visited Berlin, part {index} of {uuid.uuid4()}." for index in range(count)]
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


async def add_mention(
    session_factory: async_sessionmaker[AsyncSession],
    chunk: DocumentChunk,
    chunk_text_hash: str | None = None,
) -> None:
    async with session_factory() as session:
        entity = await session.scalar(select(Entity).where(Entity.normalized_name == "merkel"))
        if entity is None:
            entity = Entity(canonical_name="Merkel", normalized_name="merkel", entity_type="person")
            session.add(entity)
            await session.flush()
        session.add(
            EntityMention(
                entity_id=entity.id,
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                surface_text="Merkel",
                entity_type="person",
                start_char=0,
                end_char=6,
                provider=MODEL[0],
                model=MODEL[1],
                chunk_text_hash=chunk_text_hash or chunk.text_hash,
            )
        )
        await session.commit()


async def add_job(
    session_factory: async_sessionmaker[AsyncSession],
    chunk: DocumentChunk,
    status: EntityExtractionJobStatus,
) -> None:
    async with session_factory() as session:
        session.add(
            EntityExtractionJob(chunk_id=chunk.id, provider=MODEL[0], model=MODEL[1], status=status)
        )
        await session.commit()


async def jobs(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[uuid.UUID, EntityExtractionJob]:
    async with session_factory() as session:
        return {job.chunk_id: job for job in await session.scalars(select(EntityExtractionJob))}


def service(session_factory: async_sessionmaker[AsyncSession]) -> EntityExtractionQueueService:
    return EntityExtractionQueueService(session_factory, clock=lambda: NOW)


async def test_new_chunks_get_jobs(session_factory: async_sessionmaker[AsyncSession]) -> None:
    chunks = await create_chunks(session_factory, 3)

    result = await service(session_factory).queue_chunks([chunk.id for chunk in chunks], *MODEL)

    assert result == EntityQueueResult(chunks_seen=3, jobs_created=3)
    saved = await jobs(session_factory)
    assert set(saved) == {chunk.id for chunk in chunks}
    assert {job.status for job in saved.values()} == {EntityExtractionJobStatus.PENDING}


async def test_current_extraction_is_skipped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with_mentions, completed_without_entities, stale, failed = await create_chunks(
        session_factory, 4
    )
    await add_mention(session_factory, with_mentions)
    # A chunk without any entities is current once its job completed.
    await add_job(session_factory, completed_without_entities, EntityExtractionJobStatus.COMPLETED)
    await add_mention(session_factory, stale, chunk_text_hash="0" * 64)
    await add_job(session_factory, stale, EntityExtractionJobStatus.COMPLETED)
    await add_job(session_factory, failed, EntityExtractionJobStatus.FAILED)

    result = await service(session_factory).queue_chunks(
        [with_mentions.id, completed_without_entities.id, stale.id, failed.id], *MODEL
    )

    assert result == EntityQueueResult(chunks_seen=4, jobs_created=2, already_extracted=2)
    saved = await jobs(session_factory)
    assert with_mentions.id not in saved
    assert saved[completed_without_entities.id].status is EntityExtractionJobStatus.COMPLETED
    for chunk in (stale, failed):
        assert saved[chunk.id].status is EntityExtractionJobStatus.PENDING
        assert saved[chunk.id].available_at == NOW


@pytest.mark.parametrize(
    "status", [EntityExtractionJobStatus.PENDING, EntityExtractionJobStatus.RUNNING]
)
async def test_active_job_is_not_duplicated(
    session_factory: async_sessionmaker[AsyncSession], status: EntityExtractionJobStatus
) -> None:
    [chunk] = await create_chunks(session_factory, 1)
    await add_job(session_factory, chunk, status)

    result = await service(session_factory).queue_chunks([chunk.id], *MODEL)

    assert result == EntityQueueResult(chunks_seen=1, already_queued=1)


async def test_other_models_get_their_own_jobs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    [chunk] = await create_chunks(session_factory, 1)
    await add_mention(session_factory, chunk)

    result = await service(session_factory).queue_chunks([chunk.id], "test", "ner-2")

    assert result == EntityQueueResult(chunks_seen=1, jobs_created=1)


async def test_backlog_is_bounded_and_moves_on(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunks = await create_chunks(session_factory, 5)

    first = await service(session_factory).queue_backlog(*MODEL, limit=2, page_size=2)
    second = await service(session_factory).queue_backlog(*MODEL, limit=10, page_size=2)

    assert first == EntityQueueResult(chunks_seen=2, jobs_created=2)
    assert second == EntityQueueResult(chunks_seen=5, jobs_created=3, already_queued=2)
    assert set(await jobs(session_factory)) == {chunk.id for chunk in chunks}


async def test_backlog_for_one_document(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    mine = await create_chunks(session_factory, 2)
    await create_chunks(session_factory, 3)

    result = await service(session_factory).queue_backlog(*MODEL, document_id=mine[0].document_id)

    assert result.jobs_created == 2
    with pytest.raises(Exception, match="Document was not found"):
        await service(session_factory).queue_backlog(*MODEL, document_id=uuid.uuid4())


async def claim(
    session_factory: async_sessionmaker[AsyncSession], now: datetime = NOW
) -> EntityExtractionJob | None:
    async with session_factory() as session:
        job = await EntityExtractionJobRepository(session).claim_next(now, [MODEL])
        await session.commit()
    return job


async def queued(session_factory: async_sessionmaker[AsyncSession], count: int) -> None:
    chunks = await create_chunks(session_factory, count)
    await EntityExtractionQueueService(
        session_factory, clock=lambda: NOW - timedelta(minutes=1)
    ).queue_chunks([chunk.id for chunk in chunks], *MODEL)


async def test_claim_heartbeat_and_complete(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await queued(session_factory, 1)

    job = await claim(session_factory)

    assert job is not None and job.lease_token is not None
    assert (job.status, job.attempt_count) == (EntityExtractionJobStatus.RUNNING, 1)
    assert job.lease_expires_at == NOW + timedelta(minutes=5)
    async with session_factory() as session:
        repository = EntityExtractionJobRepository(session)
        assert await repository.heartbeat(job.id, uuid.uuid4(), NOW) is False
        assert await repository.heartbeat(job.id, job.lease_token, NOW + timedelta(minutes=1))
        finished = await repository.mark_completed(job.id, job.lease_token, NOW)
        await session.commit()
    assert (finished.status, finished.lease_token) == (EntityExtractionJobStatus.COMPLETED, None)


async def test_only_registered_models_are_claimed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await queued(session_factory, 1)

    async with session_factory() as session:
        repository = EntityExtractionJobRepository(session)
        assert await repository.claim_next(NOW, [("test", "other")]) is None
        assert await repository.claim_next(NOW, []) is None


async def test_recovery_and_takeover(session_factory: async_sessionmaker[AsyncSession]) -> None:
    await queued(session_factory, 1)
    old = await claim(session_factory)
    assert old is not None and old.lease_token is not None

    async with session_factory() as session:
        [recovered] = await EntityExtractionJobRepository(session).recover_stale(LATER, 10)
        await session.commit()
    assert (recovered.status, recovered.lease_token) == (EntityExtractionJobStatus.PENDING, None)
    new = await claim(session_factory, LATER)
    assert new is not None and new.lease_token != old.lease_token

    async with session_factory() as session:
        with pytest.raises(JobNotHeldError):
            await EntityExtractionJobRepository(session).mark_failed(
                old.id, old.lease_token, LATER, "Too late."
            )


async def test_workers_claiming_at_the_same_time_get_different_jobs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await queued(session_factory, 3)

    claimed = await asyncio.gather(*(claim(session_factory) for _ in range(5)))

    ids = [job.id for job in claimed if job is not None]
    assert len(ids) == len(set(ids)) == 3
