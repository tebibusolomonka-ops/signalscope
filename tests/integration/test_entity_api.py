import hashlib
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_entities import FakeEntityExtractor
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.queue import EntityExtractionQueueService
from signalscope.domain.entities.worker import EntityExtractionWorker
from signalscope.domain.sources.model import Source, SourceType
from signalscope.entities.registry import EntityExtractorRegistry

pytestmark = pytest.mark.anyio


async def extract(
    session_factory: async_sessionmaker[AsyncSession], *texts: str
) -> list[DocumentChunk]:
    """Store a document with one chunk per text and run the fake extraction on it."""
    chunks = [
        TextChunk(
            position=index,
            text=value,
            start_char=0,
            end_char=len(value),
            text_hash=hashlib.sha256(value.encode()).hexdigest(),
            metadata={"page_number": index + 1},
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
    await EntityExtractionQueueService(session_factory).queue_chunks(
        [chunk.id for chunk in saved], "test", "known-words"
    )
    registry = EntityExtractorRegistry()
    registry.register(FakeEntityExtractor())
    worker = EntityExtractionWorker(session_factory, registry)
    while (await worker.run_once()).job is not None:
        pass
    return saved


async def get(client: httpx.AsyncClient, path: str, **params: Any) -> dict[str, Any]:
    response = await client.get(path, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_empty(client: httpx.AsyncClient) -> None:
    assert await get(client, "/entities") == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_list_by_name(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await extract(session_factory, "Merkel met Macron in Berlin.", "Merkel again.")

    page = await get(client, "/entities")

    assert [item["canonical_name"] for item in page["items"]] == ["Berlin", "Macron", "Merkel"]
    merkel = page["items"][2]
    assert (merkel["entity_type"], merkel["normalized_name"], merkel["mention_count"]) == (
        "person",
        "merkel",
        2,
    )


async def test_name_search_and_type_filter(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await extract(session_factory, "Merkel met Macron in Berlin.")

    by_name = await get(client, "/entities", query="  MAC ")
    by_type = await get(client, "/entities", entity_type="person")
    nothing = await get(client, "/entities", query="100%")

    assert [item["canonical_name"] for item in by_name["items"]] == ["Macron"]
    assert [item["canonical_name"] for item in by_type["items"]] == ["Macron", "Merkel"]
    assert nothing["total"] == 0


async def test_pagination(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await extract(session_factory, "Merkel met Macron in Berlin.")

    page = await get(client, "/entities", limit=2, offset=1)

    assert [item["canonical_name"] for item in page["items"]] == ["Macron", "Merkel"]
    assert (page["total"], page["limit"], page["offset"]) == (3, 2, 1)


async def test_detail(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    first, second = await extract(session_factory, "Merkel spoke.", "Then Merkel left.")
    [merkel] = (await get(client, "/entities", query="merkel"))["items"]

    detail = await get(client, f"/entities/{merkel['id']}")

    assert detail["entity"]["id"] == merkel["id"]
    assert detail["mention_count"] == 2
    assert [
        (item["chunk_id"], item["start_char"], item["end_char"], item["chunk_metadata"])
        for item in detail["mentions"]
    ] == [
        (str(first.id), 0, 6, {"page_number": 1}),
        (str(second.id), 5, 11, {"page_number": 2}),
    ]
    mention = detail["mentions"][0]
    assert (mention["surface_text"], mention["confidence"]) == ("Merkel", 0.75)
    assert (mention["provider"], mention["model"]) == ("test", "known-words")
    assert mention["document_id"] == str(first.document_id)


async def test_unknown_entity(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/entities/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Entity was not found."}}
