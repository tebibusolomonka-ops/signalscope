import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tenancy_helpers import Tenants, add_document, add_source, make_tenants

pytestmark = pytest.mark.anyio


async def chunky_document(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID | None
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    source = await add_source(session_factory, organization_id, "Harbour feed")
    texts = [f"Chunk {index} about the harbour." for index in range(5)]
    document, chunk_ids = await add_document(session_factory, source, "Storm report", texts)
    return document, chunk_ids


async def test_chunks_are_paged_in_order(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a = tenants.a
    document, chunk_ids = await chunky_document(session_factory, a.id)

    first = await auth_client.get(
        f"/documents/{document}/chunks?{a.query}&limit=2", headers=a.headers["viewer"]
    )
    second = await auth_client.get(
        f"/documents/{document}/chunks?{a.query}&limit=2&offset=2", headers=a.headers["viewer"]
    )

    assert first.status_code == 200, first.text
    body = first.json()
    assert (body["total"], body["limit"], body["offset"]) == (5, 2, 0)
    assert [item["position"] for item in body["items"]] == [0, 1]
    assert body["items"][0]["chunk_id"] == str(chunk_ids[0])
    assert body["items"][0]["text"] == "Chunk 0 about the harbour."
    assert "chunk_metadata" in body["items"][0]
    assert [item["position"] for item in second.json()["items"]] == [2, 3]


async def test_chunks_are_tenant_scoped(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a, b = tenants.a, tenants.b
    document, _ = await chunky_document(session_factory, a.id)
    legacy_document, _ = await chunky_document(session_factory, None)

    other = await auth_client.get(
        f"/documents/{document}/chunks?{b.query}", headers=b.headers["owner"]
    )
    unknown = await auth_client.get(
        f"/documents/{uuid.uuid4()}/chunks?{a.query}", headers=a.headers["viewer"]
    )
    legacy_as_user = await auth_client.get(
        f"/documents/{legacy_document}/chunks?{a.query}", headers=a.headers["owner"]
    )
    legacy_as_system = await auth_client.get(
        f"/documents/{legacy_document}/chunks", headers=tenants.system
    )

    assert other.status_code == 404
    assert unknown.status_code == 404
    assert legacy_as_user.status_code == 404
    assert legacy_as_system.status_code == 200
    assert legacy_as_system.json()["total"] == 5


async def test_chunks_without_authentication(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    document, _ = await chunky_document(session_factory, None)

    response = await client.get(f"/documents/{document}/chunks")

    assert response.status_code == 200
    assert response.json()["total"] == 5


async def test_direct_chunk_lookup(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a, b = tenants.a, tenants.b
    document, chunk_ids = await chunky_document(session_factory, a.id)
    other_document, other_chunks = await chunky_document(session_factory, a.id)

    found = await auth_client.get(
        f"/documents/{document}/chunks/{chunk_ids[2]}?{a.query}", headers=a.headers["viewer"]
    )
    wrong_document = await auth_client.get(
        f"/documents/{document}/chunks/{other_chunks[0]}?{a.query}", headers=a.headers["viewer"]
    )
    unknown = await auth_client.get(
        f"/documents/{document}/chunks/{uuid.uuid4()}?{a.query}", headers=a.headers["viewer"]
    )
    other_org = await auth_client.get(
        f"/documents/{document}/chunks/{chunk_ids[2]}?{b.query}", headers=b.headers["owner"]
    )

    assert found.status_code == 200, found.text
    body = found.json()
    assert body["chunk_id"] == str(chunk_ids[2])
    assert body["position"] == 2
    assert body["text"] == "Chunk 2 about the harbour."
    assert wrong_document.status_code == 404
    assert unknown.status_code == 404
    assert other_org.status_code == 404


async def test_direct_chunk_lookup_legacy_and_auth_off(
    auth_client: httpx.AsyncClient,
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    legacy_document, legacy_chunks = await chunky_document(session_factory, None)

    as_user = await auth_client.get(
        f"/documents/{legacy_document}/chunks/{legacy_chunks[0]}?{tenants.a.query}",
        headers=tenants.a.headers["owner"],
    )
    as_system = await auth_client.get(
        f"/documents/{legacy_document}/chunks/{legacy_chunks[0]}", headers=tenants.system
    )
    open_document, open_chunks = await chunky_document(session_factory, None)
    without_auth = await client.get(f"/documents/{open_document}/chunks/{open_chunks[0]}")

    assert as_user.status_code == 404
    assert as_system.status_code == 200
    assert without_auth.status_code == 200
