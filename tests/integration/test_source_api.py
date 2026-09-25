import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.model import Document
from signalscope.domain.ingestion.model import IngestionRun

pytestmark = pytest.mark.anyio

RSS_SOURCE = {"type": "rss", "name": "Example feed", "url": "https://example.com/rss"}


async def create_source(client: httpx.AsyncClient, data: dict[str, Any]) -> dict[str, Any]:
    response = await client.post("/sources", json=data)
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


async def test_create_source(client: httpx.AsyncClient) -> None:
    source = await create_source(client, RSS_SOURCE)

    assert uuid.UUID(source["id"])
    assert source["type"] == "rss"
    assert source["name"] == "Example feed"
    assert source["url"] == "https://example.com/rss"
    assert source["created_at"] == source["updated_at"]


async def test_list_sources_uses_default_page(client: httpx.AsyncClient) -> None:
    first = await create_source(client, {"type": "upload", "name": "Uploads"})
    second = await create_source(client, RSS_SOURCE)

    response = await client.get("/sources")

    assert response.status_code == 200
    assert response.json() == {"items": [first, second], "total": 2, "limit": 50, "offset": 0}


async def test_list_sources_with_limit_and_offset(client: httpx.AsyncClient) -> None:
    sources = [
        await create_source(client, {"type": "upload", "name": f"Uploads {number}"})
        for number in range(5)
    ]

    response = await client.get("/sources", params={"limit": 2, "offset": 2})

    assert response.json() == {"items": sources[2:4], "total": 5, "limit": 2, "offset": 2}


async def test_list_sources_past_the_end_is_empty(client: httpx.AsyncClient) -> None:
    await create_source(client, RSS_SOURCE)

    response = await client.get("/sources", params={"offset": 10})

    assert response.json() == {"items": [], "total": 1, "limit": 50, "offset": 10}


async def test_list_sources_when_there_are_none(client: httpx.AsyncClient) -> None:
    response = await client.get("/sources")

    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_get_source(client: httpx.AsyncClient) -> None:
    source = await create_source(client, RSS_SOURCE)

    response = await client.get(f"/sources/{source['id']}")

    assert response.status_code == 200
    assert response.json() == source


async def test_delete_source(client: httpx.AsyncClient) -> None:
    source = await create_source(client, RSS_SOURCE)

    response = await client.delete(f"/sources/{source['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert (await client.get(f"/sources/{source['id']}")).status_code == 404


@pytest.mark.parametrize("method", ["GET", "DELETE"])
async def test_unknown_source_returns_404(client: httpx.AsyncClient, method: str) -> None:
    response = await client.request(method, f"/sources/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Source was not found."}}


@pytest.mark.parametrize("dependent", [Document, IngestionRun])
async def test_source_in_use_cannot_be_deleted(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    dependent: type[Document | IngestionRun],
) -> None:
    source = await create_source(client, RSS_SOURCE)
    async with session_factory() as session:
        session.add(dependent(source_id=uuid.UUID(source["id"])))
        await session.commit()

    response = await client.delete(f"/sources/{source['id']}")

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "conflict",
            "message": "Source has documents or ingestion runs and cannot be deleted.",
        },
    }
