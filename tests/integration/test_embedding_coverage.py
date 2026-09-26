import hashlib
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import NotFoundError
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_coverage import (
    EmbeddingCoverage,
    EmbeddingCoverageService,
)
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

PROVIDER = "test"
MODEL = "tiny-3"


async def create_document(
    session_factory: async_sessionmaker[AsyncSession], count: int
) -> tuple[Document, list[DocumentChunk]]:
    texts = [f"Chunk {index}." for index in range(count)]
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
        return document, await repository.list_by_document(document.id)


async def add_embedding(
    session_factory: async_sessionmaker[AsyncSession],
    chunk: DocumentChunk,
    model: str = MODEL,
    chunk_text_hash: str | None = None,
) -> None:
    async with session_factory() as session:
        session.add(
            ChunkEmbedding(
                chunk_id=chunk.id,
                provider=PROVIDER,
                model=model,
                dimensions=3,
                chunk_text_hash=chunk_text_hash or chunk.text_hash,
                embedding=[1.0, 0.0, 0.0],
            )
        )
        await session.commit()


async def add_job(
    session_factory: async_sessionmaker[AsyncSession],
    chunk: DocumentChunk,
    status: EmbeddingJobStatus,
    model: str = MODEL,
) -> None:
    async with session_factory() as session:
        session.add(EmbeddingJob(chunk_id=chunk.id, provider=PROVIDER, model=model, status=status))
        await session.commit()


def coverage(
    chunks: int = 0, embedded: int = 0, pending: int = 0, failed: int = 0
) -> EmbeddingCoverage:
    return EmbeddingCoverage(
        chunk_count=chunks, embedded_count=embedded, pending_count=pending, failed_count=failed
    )


async def test_document_without_chunks(session_factory: async_sessionmaker[AsyncSession]) -> None:
    document, _ = await create_document(session_factory, 0)

    result = await EmbeddingCoverageService(session_factory).for_document(
        document.id, PROVIDER, MODEL
    )

    assert result == coverage()


async def test_unknown_document(session_factory: async_sessionmaker[AsyncSession]) -> None:
    with pytest.raises(NotFoundError):
        await EmbeddingCoverageService(session_factory).for_document(uuid.uuid4(), PROVIDER, MODEL)


async def test_nothing_embedded(session_factory: async_sessionmaker[AsyncSession]) -> None:
    document, _ = await create_document(session_factory, 3)

    result = await EmbeddingCoverageService(session_factory).for_document(
        document.id, PROVIDER, MODEL
    )

    assert result == coverage(chunks=3)


async def test_partly_embedded(session_factory: async_sessionmaker[AsyncSession]) -> None:
    document, chunks = await create_document(session_factory, 3)
    await add_embedding(session_factory, chunks[0])
    # An embedding of older text does not count.
    await add_embedding(session_factory, chunks[1], chunk_text_hash="0" * 64)

    result = await EmbeddingCoverageService(session_factory).for_document(
        document.id, PROVIDER, MODEL
    )

    assert result == coverage(chunks=3, embedded=1)


async def test_fully_embedded(session_factory: async_sessionmaker[AsyncSession]) -> None:
    document, chunks = await create_document(session_factory, 2)
    for chunk in chunks:
        await add_embedding(session_factory, chunk)
        await add_job(session_factory, chunk, EmbeddingJobStatus.COMPLETED)

    result = await EmbeddingCoverageService(session_factory).for_document(
        document.id, PROVIDER, MODEL
    )

    assert result == coverage(chunks=2, embedded=2)


async def test_pending_and_failed_jobs(session_factory: async_sessionmaker[AsyncSession]) -> None:
    document, chunks = await create_document(session_factory, 4)
    await add_job(session_factory, chunks[0], EmbeddingJobStatus.PENDING)
    await add_job(session_factory, chunks[1], EmbeddingJobStatus.RUNNING)
    await add_job(session_factory, chunks[2], EmbeddingJobStatus.FAILED)

    result = await EmbeddingCoverageService(session_factory).for_document(
        document.id, PROVIDER, MODEL
    )

    assert result == coverage(chunks=4, pending=2, failed=1)


async def test_other_models_and_documents_are_not_counted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document, [chunk] = await create_document(session_factory, 1)
    await add_embedding(session_factory, chunk, model="other")
    await add_job(session_factory, chunk, EmbeddingJobStatus.FAILED, model="other")
    _, [elsewhere] = await create_document(session_factory, 1)
    await add_embedding(session_factory, elsewhere)
    service = EmbeddingCoverageService(session_factory)

    assert await service.for_document(document.id, PROVIDER, MODEL) == coverage(chunks=1)
    assert await service.for_document(document.id, PROVIDER, "other") == coverage(
        chunks=1, embedded=1, failed=1
    )


async def test_overall(session_factory: async_sessionmaker[AsyncSession]) -> None:
    _, first = await create_document(session_factory, 2)
    _, second = await create_document(session_factory, 1)
    await add_embedding(session_factory, first[0])
    await add_job(session_factory, second[0], EmbeddingJobStatus.PENDING)

    result = await EmbeddingCoverageService(session_factory).overall(PROVIDER, MODEL)

    assert result == coverage(chunks=3, embedded=1, pending=1)
