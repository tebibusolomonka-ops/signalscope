import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio


async def create_chunks(
    session_factory: async_sessionmaker[AsyncSession], count: int
) -> list[DocumentChunk]:
    texts = [f"Report part {index} of {uuid.uuid4()}." for index in range(count)]
    chunks = [
        TextChunk(
            position=index,
            text=text,
            start_char=0,
            end_char=len(text),
            text_hash=hashlib.sha256(text.encode()).hexdigest(),
            metadata={"page_number": index + 1},
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


async def add_event(
    session_factory: async_sessionmaker[AsyncSession],
    title: str,
    event_type: str = "flood",
    occurred_at: datetime | None = None,
    chunks: list[DocumentChunk] | None = None,
) -> str:
    async with session_factory() as session:
        event = Event(event_type=event_type, title=title, occurred_at=occurred_at)
        session.add(event)
        await session.flush()
        for chunk in chunks or []:
            session.add(
                EventEvidence(
                    event_id=event.id,
                    chunk_id=chunk.id,
                    confidence=0.7,
                    provider="test",
                    model="events-1",
                )
            )
        await session.commit()
        return str(event.id)


def day(number: int) -> datetime:
    return datetime(2026, 9, number, tzinfo=UTC)


async def get(client: httpx.AsyncClient, path: str, **params: Any) -> dict[str, Any]:
    response = await client.get(path, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def titles(client: httpx.AsyncClient, **params: Any) -> list[str]:
    return [item["title"] for item in (await get(client, "/events", **params))["items"]]


async def test_empty(client: httpx.AsyncClient) -> None:
    assert await get(client, "/events") == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_time_order_with_unknown_times_last(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_event(session_factory, "No time")
    await add_event(session_factory, "Later", occurred_at=day(20))
    await add_event(session_factory, "Earlier", occurred_at=day(10))

    assert await titles(client) == ["Earlier", "Later", "No time"]


async def test_type_filter(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_event(session_factory, "River flood")
    await add_event(session_factory, "Vote", event_type="election")

    assert await titles(client, event_type=" FLOOD ") == ["River flood"]


async def test_time_filters(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    for number in (5, 10, 15):
        await add_event(session_factory, f"Day {number}", occurred_at=day(number))
    await add_event(session_factory, "No time")

    assert await titles(client, occurred_from=day(10).isoformat()) == ["Day 10", "Day 15"]
    assert await titles(client, occurred_to=day(10).isoformat()) == ["Day 5"]
    assert await titles(
        client, occurred_from=day(6).isoformat(), occurred_to=day(15).isoformat()
    ) == ["Day 10"]


async def test_time_range_must_be_in_order(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/events", params={"occurred_from": day(10).isoformat(), "occurred_to": day(5).isoformat()}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"


async def test_pagination(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    for number in range(1, 4):
        await add_event(session_factory, f"Day {number}", occurred_at=day(number))

    page = await get(client, "/events", limit=2, offset=1)

    assert [item["title"] for item in page["items"]] == ["Day 2", "Day 3"]
    assert (page["total"], page["limit"], page["offset"]) == (3, 2, 1)


async def test_detail(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    first, second = await create_chunks(session_factory, 2)
    event_id = await add_event(
        session_factory, "River flood", occurred_at=day(21), chunks=[first, second]
    )

    detail = await get(client, f"/events/{event_id}")

    assert detail["event"]["id"] == event_id
    assert detail["event"]["occurred_at"] == "2026-09-21T00:00:00Z"
    assert [
        (item["chunk_id"], item["document_id"], item["chunk_metadata"])
        for item in detail["evidence"]
    ] == [
        (str(first.id), str(first.document_id), {"page_number": 1}),
        (str(second.id), str(second.document_id), {"page_number": 2}),
    ]
    assert (detail["evidence"][0]["confidence"], detail["evidence"][0]["model"]) == (
        0.7,
        "events-1",
    )


async def test_unknown_event(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/events/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Event was not found."}}
