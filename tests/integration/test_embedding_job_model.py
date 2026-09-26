import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import chunk_text
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

TEXT = "Climate policy for coastal cities."


async def create_chunk(session_factory: async_sessionmaker[AsyncSession]) -> DocumentChunk:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, content=TEXT)
        session.add(document)
        await session.flush()
        await DocumentChunkRepository(session).replace_for_document(document.id, chunk_text(TEXT))
        await session.commit()
        [chunk] = await DocumentChunkRepository(session).list_by_document(document.id)
    return chunk


def job_for(chunk: DocumentChunk, **values: Any) -> EmbeddingJob:
    fields: dict[str, Any] = {"chunk_id": chunk.id, "provider": "test", "model": "tiny-3"}
    return EmbeddingJob(**(fields | values))


async def add(session_factory: async_sessionmaker[AsyncSession], *jobs: EmbeddingJob) -> None:
    async with session_factory() as session:
        session.add_all(jobs)
        await session.commit()


async def stored(session_factory: async_sessionmaker[AsyncSession]) -> list[EmbeddingJob]:
    async with session_factory() as session:
        return list(await session.scalars(select(EmbeddingJob)))


async def test_new_job_defaults(session_factory: async_sessionmaker[AsyncSession]) -> None:
    chunk = await create_chunk(session_factory)
    before = datetime.now(UTC)

    await add(session_factory, job_for(chunk))

    [saved] = await stored(session_factory)
    assert saved.status is EmbeddingJobStatus.PENDING
    assert saved.attempt_count == 0
    assert (saved.claimed_at, saved.heartbeat_at, saved.lease_expires_at) == (None, None, None)
    assert (saved.finished_at, saved.last_error) == (None, None)
    # The database clock can differ a little from the test clock.
    assert abs((saved.available_at - before).total_seconds()) < 60


async def test_database_defaults(session_factory: async_sessionmaker[AsyncSession]) -> None:
    chunk = await create_chunk(session_factory)

    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "INSERT INTO embedding_jobs (id, chunk_id, provider, model, status) "
                    "VALUES (:id, :chunk_id, 'test', 'tiny-3', 'pending') "
                    "RETURNING attempt_count, available_at IS NOT NULL"
                ),
                {"id": uuid.uuid4(), "chunk_id": chunk.id},
            )
        ).one()

    assert tuple(row) == (0, True)


async def test_one_job_per_chunk_provider_and_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk = await create_chunk(session_factory)
    await add(session_factory, job_for(chunk))

    async with session_factory() as session:
        session.add(job_for(chunk))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_other_models_get_their_own_job(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk = await create_chunk(session_factory)

    await add(
        session_factory,
        job_for(chunk),
        job_for(chunk, model="tiny-4"),
        job_for(chunk, provider="other"),
    )

    assert len(await stored(session_factory)) == 3


@pytest.mark.parametrize(
    "values",
    [{"attempt_count": -1}, {"status": "waiting"}, {"chunk_id": uuid.uuid4()}],
    ids=["negative attempts", "unknown status", "unknown chunk"],
)
async def test_invalid_job_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, Any]
) -> None:
    chunk = await create_chunk(session_factory)
    row = {
        "id": uuid.uuid4(),
        "chunk_id": chunk.id,
        "status": "pending",
        "attempt_count": 0,
    } | values

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO embedding_jobs "
                    "(id, chunk_id, provider, model, status, attempt_count) "
                    "VALUES (:id, :chunk_id, 'test', 'tiny-3', :status, :attempt_count)"
                ),
                row,
            )


async def test_jobs_go_away_with_their_chunk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk = await create_chunk(session_factory)
    await add(session_factory, job_for(chunk))

    async with session_factory() as session:
        await session.execute(delete(DocumentChunk).where(DocumentChunk.id == chunk.id))
        await session.commit()

    assert await stored(session_factory) == []


async def test_replacing_chunks_removes_their_jobs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk = await create_chunk(session_factory)
    await add(session_factory, job_for(chunk))

    async with session_factory() as session:
        await DocumentChunkRepository(session).replace_for_document(
            chunk.document_id, chunk_text("Completely different text now.")
        )
        await session.commit()

    assert await stored(session_factory) == []


async def test_deleting_the_document_removes_its_jobs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk = await create_chunk(session_factory)
    await add(session_factory, job_for(chunk))

    async with session_factory() as session:
        await session.execute(delete(Document).where(Document.id == chunk.document_id))
        await session.commit()

    assert await stored(session_factory) == []


async def test_foreign_key(database_engine: AsyncEngine) -> None:
    async with database_engine.connect() as connection:
        foreign_keys = await connection.run_sync(
            lambda sync: inspect(sync).get_foreign_keys("embedding_jobs")
        )

    [key] = foreign_keys
    assert (key["constrained_columns"], key["referred_table"]) == (["chunk_id"], "document_chunks")
    assert key["options"]["ondelete"] == "CASCADE"


async def test_queue_index(database_engine: AsyncEngine) -> None:
    async with database_engine.connect() as connection:
        indexes = await connection.run_sync(
            lambda sync: inspect(sync).get_indexes("embedding_jobs")
        )

    columns = {index["name"]: index["column_names"] for index in indexes}
    assert columns["ix_embedding_jobs_status_available_at"] == ["status", "available_at"]
