import hashlib
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

E5 = {"provider": "sentence_transformers", "model": "intfloat/multilingual-e5-small"}


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


async def embed(
    session_factory: async_sessionmaker[AsyncSession], chunk: DocumentChunk, **values: Any
) -> None:
    fields: dict[str, Any] = E5 | {
        "chunk_id": chunk.id,
        "dimensions": 3,
        "chunk_text_hash": chunk.text_hash,
        "embedding": [1.0, 0.0, 0.0],
    }
    async with session_factory() as session:
        session.add(ChunkEmbedding(**(fields | values)))
        await session.commit()


async def add_job(
    session_factory: async_sessionmaker[AsyncSession],
    chunk: DocumentChunk,
    status: EmbeddingJobStatus,
) -> None:
    async with session_factory() as session:
        session.add(EmbeddingJob(chunk_id=chunk.id, status=status, **E5))
        await session.commit()


async def coverage(client: httpx.AsyncClient, **params: str) -> dict[str, Any]:
    response = await client.get("/embeddings/coverage", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_empty_database(client: httpx.AsyncClient) -> None:
    assert await coverage(client) == E5 | {
        "document_id": None,
        "chunk_count": 0,
        "embedded_count": 0,
        "pending_count": 0,
        "failed_count": 0,
        "coverage": None,
    }


async def test_partial_coverage(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    embedded, pending, failed, missing = await create_document(session_factory, 4)
    await embed(session_factory, embedded)
    await add_job(session_factory, pending, EmbeddingJobStatus.PENDING)
    await add_job(session_factory, failed, EmbeddingJobStatus.FAILED)
    # Embeddings from other models and of older text do not count.
    await embed(session_factory, missing, model="other")
    await embed(session_factory, pending, chunk_text_hash="0" * 64)

    body = await coverage(client)

    assert (body["chunk_count"], body["embedded_count"]) == (4, 1)
    assert (body["pending_count"], body["failed_count"]) == (1, 1)
    assert body["coverage"] == 0.25


async def test_complete_coverage(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    for chunk in await create_document(session_factory, 2):
        await embed(session_factory, chunk)

    body = await coverage(client)

    assert (body["chunk_count"], body["embedded_count"], body["coverage"]) == (2, 2, 1.0)


async def test_one_document(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    mine = await create_document(session_factory, 2)
    others = await create_document(session_factory, 3)
    await embed(session_factory, mine[0])
    for chunk in others:
        await embed(session_factory, chunk)
    document_id = str(mine[0].document_id)

    body = await coverage(client, document_id=document_id)

    assert body["document_id"] == document_id
    assert (body["chunk_count"], body["embedded_count"], body["coverage"]) == (2, 1, 0.5)


async def test_unknown_document(client: httpx.AsyncClient) -> None:
    response = await client.get("/embeddings/coverage", params={"document_id": str(uuid.uuid4())})

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Document was not found."}}
