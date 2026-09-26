import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import chunk_text
from signalscope.domain.documents.model import Document
from signalscope.domain.events.job import EventExtractionJob, EventExtractionJobStatus
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

TEXT = "Heavy rain flooded the harbour district."


async def create_chunk(session_factory: async_sessionmaker[AsyncSession]) -> DocumentChunk:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, content=TEXT)
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunk_text(TEXT))
        await session.commit()
        [chunk] = await repository.list_by_document(document.id)
    return chunk


def job_for(chunk: DocumentChunk, **values: Any) -> EventExtractionJob:
    fields: dict[str, Any] = {"chunk_id": chunk.id, "provider": "test", "model": "events-1"}
    return EventExtractionJob(**(fields | values))


async def stored(session_factory: async_sessionmaker[AsyncSession]) -> list[EventExtractionJob]:
    async with session_factory() as session:
        return list(await session.scalars(select(EventExtractionJob)))


async def test_new_job_defaults(session_factory: async_sessionmaker[AsyncSession]) -> None:
    chunk = await create_chunk(session_factory)
    before = datetime.now(UTC)

    async with session_factory() as session:
        session.add(job_for(chunk))
        await session.commit()

    [saved] = await stored(session_factory)
    assert saved.status is EventExtractionJobStatus.PENDING
    assert saved.attempt_count == 0
    assert (saved.claimed_at, saved.lease_expires_at, saved.lease_token) == (None, None, None)
    assert abs((saved.available_at - before).total_seconds()) < 60


async def test_one_job_per_chunk_provider_and_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk = await create_chunk(session_factory)
    async with session_factory() as session:
        session.add_all([job_for(chunk), job_for(chunk, model="events-2")])
        await session.commit()

    async with session_factory() as session:
        session.add(job_for(chunk))
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.parametrize(
    "values",
    [{"attempt_count": -1}, {"status": "waiting"}, {"chunk_id": uuid.uuid4()}],
    ids=["negative attempts", "unknown status", "unknown chunk"],
)
async def test_invalid_job_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, Any]
) -> None:
    chunk = await create_chunk(session_factory)
    row = {"id": uuid.uuid4(), "chunk_id": chunk.id, "status": "pending", "attempt_count": 0}

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO event_extraction_jobs "
                    "(id, chunk_id, provider, model, status, attempt_count) "
                    "VALUES (:id, :chunk_id, 'test', 'events-1', :status, :attempt_count)"
                ),
                row | values,
            )


async def test_jobs_go_away_with_their_chunk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk = await create_chunk(session_factory)
    async with session_factory() as session:
        session.add(job_for(chunk))
        await session.commit()

    async with session_factory() as session:
        await DocumentChunkRepository(session).replace_for_document(
            chunk.document_id, chunk_text("Different text.")
        )
        await session.commit()

    assert await stored(session_factory) == []


async def test_queue_index(database_engine: AsyncEngine) -> None:
    async with database_engine.connect() as connection:
        indexes = await connection.run_sync(
            lambda sync: inspect(sync).get_indexes("event_extraction_jobs")
        )

    columns = {index["name"]: index["column_names"] for index in indexes}
    assert columns["ix_event_extraction_jobs_status_available_at"] == ["status", "available_at"]
