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
from signalscope.domain.entities.job import EntityExtractionJob, EntityExtractionJobStatus
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

GLINER = {"provider": "gliner", "model": "urchade/gliner_multi-v2.1"}


async def create_chunks(
    session_factory: async_sessionmaker[AsyncSession], count: int
) -> list[DocumentChunk]:
    texts = [f"Merkel spoke, part {index} of {uuid.uuid4()}." for index in range(count)]
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


async def add_job(
    session_factory: async_sessionmaker[AsyncSession],
    chunk: DocumentChunk,
    status: EntityExtractionJobStatus,
    model: str = GLINER["model"],
) -> None:
    async with session_factory() as session:
        session.add(
            EntityExtractionJob(
                chunk_id=chunk.id, provider=GLINER["provider"], model=model, status=status
            )
        )
        await session.commit()


async def add_mention(
    session_factory: async_sessionmaker[AsyncSession], chunk: DocumentChunk
) -> None:
    async with session_factory() as session:
        entity = Entity(
            canonical_name="Merkel", normalized_name=f"merkel {chunk.id}", entity_type="person"
        )
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
                chunk_text_hash=chunk.text_hash,
                **GLINER,
            )
        )
        await session.commit()


async def coverage(client: httpx.AsyncClient, **params: str) -> dict[str, Any]:
    response = await client.get("/entities/coverage", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_empty(client: httpx.AsyncClient) -> None:
    assert await coverage(client) == GLINER | {
        "document_id": None,
        "chunk_count": 0,
        "extracted_count": 0,
        "pending_count": 0,
        "failed_count": 0,
        "coverage": None,
    }


async def test_partial(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    done, with_mentions, pending, failed, other_model = await create_chunks(session_factory, 5)
    await add_job(session_factory, done, EntityExtractionJobStatus.COMPLETED)
    await add_mention(session_factory, with_mentions)
    await add_job(session_factory, pending, EntityExtractionJobStatus.PENDING)
    await add_job(session_factory, failed, EntityExtractionJobStatus.FAILED)
    await add_job(session_factory, other_model, EntityExtractionJobStatus.COMPLETED, "other")

    body = await coverage(client)

    assert (body["chunk_count"], body["extracted_count"]) == (5, 2)
    assert (body["pending_count"], body["failed_count"]) == (1, 1)
    assert body["coverage"] == 0.4


async def test_complete(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    for chunk in await create_chunks(session_factory, 2):
        await add_job(session_factory, chunk, EntityExtractionJobStatus.COMPLETED)

    body = await coverage(client)

    assert (body["extracted_count"], body["coverage"]) == (2, 1.0)


async def test_one_document(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    mine = await create_chunks(session_factory, 2)
    for chunk in await create_chunks(session_factory, 3):
        await add_job(session_factory, chunk, EntityExtractionJobStatus.COMPLETED)
    await add_job(session_factory, mine[0], EntityExtractionJobStatus.COMPLETED)

    body = await coverage(client, document_id=str(mine[0].document_id))

    assert body["document_id"] == str(mine[0].document_id)
    assert (body["chunk_count"], body["extracted_count"], body["coverage"]) == (2, 1, 0.5)


async def test_unknown_document(client: httpx.AsyncClient) -> None:
    response = await client.get("/entities/coverage", params={"document_id": str(uuid.uuid4())})

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Document was not found."
