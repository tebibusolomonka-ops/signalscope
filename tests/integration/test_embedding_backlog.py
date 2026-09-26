import dataclasses
import hashlib
import io
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.cli import queue_embeddings
from signalscope.core.errors import NotFoundError
from signalscope.core.settings import Settings
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.search.embedding_queue import EmbeddingQueueResult, EmbeddingQueueService
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

PROVIDER = "sentence_transformers"
MODEL = "intfloat/multilingual-e5-small"


async def create_document(
    session_factory: async_sessionmaker[AsyncSession], count: int
) -> list[DocumentChunk]:
    texts = [f"Chunk {index} of {uuid.uuid4()}." for index in range(count)]
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


async def add_embedding(
    session_factory: async_sessionmaker[AsyncSession],
    chunk: DocumentChunk,
    chunk_text_hash: str | None = None,
) -> None:
    async with session_factory() as session:
        session.add(
            ChunkEmbedding(
                chunk_id=chunk.id,
                provider=PROVIDER,
                model=MODEL,
                dimensions=3,
                chunk_text_hash=chunk_text_hash or chunk.text_hash,
                embedding=[1.0, 0.0, 0.0],
            )
        )
        await session.commit()


async def job_chunk_ids(session_factory: async_sessionmaker[AsyncSession]) -> set[uuid.UUID]:
    async with session_factory() as session:
        return set(await session.scalars(select(EmbeddingJob.chunk_id)))


async def backlog(
    session_factory: async_sessionmaker[AsyncSession], **options: object
) -> EmbeddingQueueResult:
    return await EmbeddingQueueService(session_factory).queue_backlog(
        PROVIDER,
        MODEL,
        **options,  # type: ignore[arg-type]
    )


async def test_empty_database(session_factory: async_sessionmaker[AsyncSession]) -> None:
    assert await backlog(session_factory) == EmbeddingQueueResult()


async def test_new_chunks_get_jobs_across_pages(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await create_document(session_factory, 3)
    second = await create_document(session_factory, 2)

    result = await backlog(session_factory, page_size=2)

    assert result == EmbeddingQueueResult(chunks_seen=5, jobs_created=5)
    assert await job_chunk_ids(session_factory) == {chunk.id for chunk in first + second}


async def test_done_chunks_are_counted_and_skipped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    embedded, queued, stale, new = await create_document(session_factory, 4)
    await add_embedding(session_factory, embedded)
    await add_embedding(session_factory, stale, chunk_text_hash="0" * 64)
    async with session_factory() as session:
        session.add(
            EmbeddingJob(
                chunk_id=queued.id,
                provider=PROVIDER,
                model=MODEL,
                status=EmbeddingJobStatus.RUNNING,
            )
        )
        await session.commit()

    result = await backlog(session_factory)

    assert result == EmbeddingQueueResult(
        chunks_seen=4, jobs_created=2, already_queued=1, already_embedded=1
    )
    assert await job_chunk_ids(session_factory) == {queued.id, stale.id, new.id}


async def test_document_filter(session_factory: async_sessionmaker[AsyncSession]) -> None:
    mine = await create_document(session_factory, 2)
    await create_document(session_factory, 3)

    result = await backlog(session_factory, document_id=mine[0].document_id)

    assert result == EmbeddingQueueResult(chunks_seen=2, jobs_created=2)
    assert await job_chunk_ids(session_factory) == {chunk.id for chunk in mine}


async def test_unknown_document(session_factory: async_sessionmaker[AsyncSession]) -> None:
    with pytest.raises(NotFoundError):
        await backlog(session_factory, document_id=uuid.uuid4())


async def test_limit_moves_on_with_each_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunks = await create_document(session_factory, 5)

    first = await backlog(session_factory, limit=2)
    second = await backlog(session_factory, limit=2)
    third = await backlog(session_factory, limit=2)

    assert (first.jobs_created, second.jobs_created, third.jobs_created) == (2, 2, 1)
    # The chunks done earlier are checked again, but skipped.
    assert second.already_queued == 2
    # Chunks are taken in document order.
    assert first == EmbeddingQueueResult(chunks_seen=2, jobs_created=2)
    assert await job_chunk_ids(session_factory) == {chunk.id for chunk in chunks}


@pytest.mark.parametrize("options", [{"limit": 0}, {"page_size": 0}])
async def test_bad_options(
    session_factory: async_sessionmaker[AsyncSession], options: dict[str, int]
) -> None:
    with pytest.raises(ValueError):
        await backlog(session_factory, **options)


@pytest.fixture
def settings(database_engine: AsyncEngine, migrated_database: Settings) -> Settings:
    return Settings(database_url=migrated_database.database_url, local_embeddings_enabled=True)


async def test_command_output(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    embedded, _, _ = await create_document(session_factory, 3)
    await add_embedding(session_factory, embedded)
    out, err = io.StringIO(), io.StringIO()

    code = await queue_embeddings(settings, out, err)

    assert (code, err.getvalue()) == (0, "")
    assert out.getvalue() == (
        "Chunks checked: 3\nJobs created: 2\nAlready embedded: 1\nAlready queued: 0\n"
    )


async def test_command_with_document_and_limit(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    chunks = await create_document(session_factory, 3)
    await create_document(session_factory, 2)
    out, err = io.StringIO(), io.StringIO()

    code = await queue_embeddings(settings, out, err, document_id=chunks[0].document_id, limit=1)

    assert code == 0
    assert "Jobs created: 1\n" in out.getvalue()
    assert await job_chunk_ids(session_factory) == {chunks[0].id}


async def test_command_with_unknown_document(settings: Settings) -> None:
    out, err = io.StringIO(), io.StringIO()

    code = await queue_embeddings(settings, out, err, document_id=uuid.uuid4())

    assert (code, out.getvalue()) == (1, "")
    assert err.getvalue() == "Error: Document was not found.\n"


async def test_command_needs_local_embeddings(settings: Settings) -> None:
    out, err = io.StringIO(), io.StringIO()
    disabled = dataclasses.replace(settings, local_embeddings_enabled=False)

    assert await queue_embeddings(disabled, out, err) == 1
    assert "SIGNALSCOPE_LOCAL_EMBEDDINGS_ENABLED" in err.getvalue()
