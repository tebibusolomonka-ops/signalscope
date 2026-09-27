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
from signalscope.domain.events.job import EventExtractionJob, EventExtractionJobStatus
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

GLINER2 = {"provider": "gliner2", "model": "fastino/gliner2.5-multi-v1"}


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
        source = Source(type=SourceType.UPLOAD, name=f"Files {uuid.uuid4()}")
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
    status: EventExtractionJobStatus,
    model: str = GLINER2["model"],
) -> None:
    async with session_factory() as session:
        session.add(
            EventExtractionJob(
                chunk_id=chunk.id, provider=GLINER2["provider"], model=model, status=status
            )
        )
        await session.commit()


async def add_evidence(
    session_factory: async_sessionmaker[AsyncSession], chunk: DocumentChunk
) -> None:
    async with session_factory() as session:
        event = Event(event_type="flood", title="River flooded")
        session.add(event)
        await session.flush()
        session.add(EventEvidence(event_id=event.id, chunk_id=chunk.id, **GLINER2))
        await session.commit()


async def coverage(client: httpx.AsyncClient, **params: str) -> dict[str, Any]:
    response = await client.get("/events/coverage", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_empty(client: httpx.AsyncClient) -> None:
    assert await coverage(client) == GLINER2 | {
        "document_id": None,
        "chunk_count": 0,
        "extracted_count": 0,
        "pending_count": 0,
        "failed_count": 0,
        "coverage_ratio": None,
    }


async def test_partial(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    done, with_events, pending, failed, other_model = await create_chunks(session_factory, 5)
    await add_job(session_factory, done, EventExtractionJobStatus.COMPLETED)
    await add_evidence(session_factory, with_events)
    await add_job(session_factory, pending, EventExtractionJobStatus.PENDING)
    await add_job(session_factory, failed, EventExtractionJobStatus.FAILED)
    await add_job(session_factory, other_model, EventExtractionJobStatus.COMPLETED, "other")

    body = await coverage(client)

    assert (body["chunk_count"], body["extracted_count"]) == (5, 2)
    assert (body["pending_count"], body["failed_count"]) == (1, 1)
    assert body["coverage_ratio"] == 0.4


async def test_complete(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    for chunk in await create_chunks(session_factory, 2):
        await add_job(session_factory, chunk, EventExtractionJobStatus.COMPLETED)

    body = await coverage(client)

    assert (body["extracted_count"], body["coverage_ratio"]) == (2, 1.0)


async def test_one_document(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    mine = await create_chunks(session_factory, 2)
    for chunk in await create_chunks(session_factory, 3):
        await add_job(session_factory, chunk, EventExtractionJobStatus.COMPLETED)
    await add_job(session_factory, mine[0], EventExtractionJobStatus.COMPLETED)

    body = await coverage(client, document_id=str(mine[0].document_id))

    assert body["document_id"] == str(mine[0].document_id)
    assert (body["chunk_count"], body["extracted_count"], body["coverage_ratio"]) == (2, 1, 0.5)


async def test_unknown_document(client: httpx.AsyncClient) -> None:
    response = await client.get("/events/coverage", params={"document_id": str(uuid.uuid4())})

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Document was not found."
