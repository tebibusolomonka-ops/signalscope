import uuid
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture
async def source_id(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/sources", json={"type": "rss", "name": "Example feed", "url": "https://example.com/rss"}
    )
    assert response.status_code == 201
    source_id: str = response.json()["id"]
    return source_id


async def create_document(client: httpx.AsyncClient, data: dict[str, Any]) -> dict[str, Any]:
    response = await client.post("/documents", json=data)
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


async def test_create_document(client: httpx.AsyncClient, source_id: str) -> None:
    document = await create_document(
        client,
        {
            "source_id": source_id,
            "external_id": "guid-1",
            "title": "An article",
            "content": "Some text.",
            "language": "en",
            "published_at": "2026-03-01T12:30:00+02:00",
        },
    )

    assert uuid.UUID(document["id"])
    assert document["source_id"] == source_id
    assert document["external_id"] == "guid-1"
    assert document["title"] == "An article"
    assert document["content"] == "Some text."
    assert document["language"] == "en"
    assert document["published_at"] == "2026-03-01T10:30:00Z"


async def test_list_documents_uses_default_page(client: httpx.AsyncClient, source_id: str) -> None:
    assert (await client.get("/documents")).json() == {
        "items": [],
        "total": 0,
        "limit": 50,
        "offset": 0,
    }

    first = await create_document(client, {"source_id": source_id, "title": "First"})
    second = await create_document(client, {"source_id": source_id, "title": "Second"})

    response = await client.get("/documents")

    assert response.status_code == 200
    assert response.json() == {"items": [first, second], "total": 2, "limit": 50, "offset": 0}


async def test_list_documents_with_limit_and_offset(
    client: httpx.AsyncClient, source_id: str
) -> None:
    documents = [
        await create_document(client, {"source_id": source_id, "title": f"Article {number}"})
        for number in range(5)
    ]

    page = (await client.get("/documents", params={"limit": 2, "offset": 2})).json()
    past_the_end = (await client.get("/documents", params={"offset": 10})).json()

    assert page == {"items": documents[2:4], "total": 5, "limit": 2, "offset": 2}
    assert past_the_end == {"items": [], "total": 5, "limit": 50, "offset": 10}


async def test_get_document(client: httpx.AsyncClient, source_id: str) -> None:
    document = await create_document(client, {"source_id": source_id})

    response = await client.get(f"/documents/{document['id']}")

    assert response.status_code == 200
    assert response.json() == document


async def test_delete_document(client: httpx.AsyncClient, source_id: str) -> None:
    document = await create_document(client, {"source_id": source_id})

    response = await client.delete(f"/documents/{document['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert (await client.get(f"/documents/{document['id']}")).status_code == 404


@pytest.mark.parametrize("method", ["GET", "DELETE"])
async def test_unknown_document_returns_404(client: httpx.AsyncClient, method: str) -> None:
    response = await client.request(method, f"/documents/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Document was not found."},
    }


async def test_create_document_for_unknown_source_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.post("/documents", json={"source_id": str(uuid.uuid4())})

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Source was not found."}}


async def test_duplicate_external_id_returns_409(client: httpx.AsyncClient, source_id: str) -> None:
    await create_document(client, {"source_id": source_id, "external_id": "guid-1"})

    response = await client.post(
        "/documents", json={"source_id": source_id, "external_id": "guid-1"}
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "conflict", "message": "Document already exists for this source."},
    }


async def test_list_documents_with_filters(client: httpx.AsyncClient, source_id: str) -> None:
    await create_document(
        client,
        {
            "source_id": source_id,
            "title": "Early",
            "language": "en",
            "published_at": "2026-03-01T10:00:00Z",
        },
    )
    await create_document(
        client,
        {
            "source_id": source_id,
            "title": "Late",
            "language": "en",
            "published_at": "2026-03-05T10:00:00Z",
        },
    )
    await create_document(client, {"source_id": source_id, "title": "German", "language": "de"})

    response = await client.get(
        "/documents",
        params={
            "source_id": source_id,
            "language": "en",
            "published_from": "2026-03-02T00:00:00+02:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [document["title"] for document in body["items"]] == ["Late"]
    assert body["total"] == 1


async def test_total_counts_filtered_documents_across_pages(
    client: httpx.AsyncClient, source_id: str
) -> None:
    for number in range(3):
        await create_document(
            client, {"source_id": source_id, "title": f"English {number}", "language": "en"}
        )
    await create_document(client, {"source_id": source_id, "title": "German", "language": "de"})

    response = await client.get("/documents", params={"language": "en", "limit": 2, "offset": 1})

    body = response.json()
    assert [document["title"] for document in body["items"]] == ["English 1", "English 2"]
    assert body["total"] == 3


async def test_list_documents_for_unknown_source_is_empty(client: httpx.AsyncClient) -> None:
    response = await client.get("/documents", params={"source_id": str(uuid.uuid4())})

    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


async def test_language_is_stored_in_lowercase_and_found_with_any_case(
    client: httpx.AsyncClient, source_id: str
) -> None:
    created = await create_document(
        client, {"source_id": source_id, "title": "Mixed case", "language": "EN-us"}
    )

    response = await client.get("/documents", params={"language": "en-US"})

    assert created["language"] == "en-us"
    assert response.json()["items"] == [created]
