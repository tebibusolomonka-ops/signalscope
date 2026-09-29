import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tenancy_helpers import Tenants, add_document, add_findings, add_source, make_tenants

pytestmark = pytest.mark.anyio


class World:
    tenants: Tenants
    shared_entity: uuid.UUID
    a_chunk: uuid.UUID
    b_chunks: list[uuid.UUID]
    b_only_entity: uuid.UUID


@pytest.fixture
async def world(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> World:
    """Porto is mentioned once in A and three times in B. Lisbon only in B."""
    found = World()
    found.tenants = await make_tenants(auth_client, session_factory)
    a_source = await add_source(session_factory, found.tenants.a.id)
    b_source = await add_source(session_factory, found.tenants.b.id)
    legacy_source = await add_source(session_factory, None)
    _, [found.a_chunk] = await add_document(session_factory, a_source, "a-doc", ["Porto a."])
    _, found.b_chunks = await add_document(session_factory, b_source, "b-doc", ["Porto b."] * 3)
    _, [legacy_chunk] = await add_document(session_factory, legacy_source, "l-doc", ["Porto l."])
    found.shared_entity, _ = await add_findings(session_factory, found.a_chunk)
    for chunk in found.b_chunks:
        await add_findings(session_factory, chunk)
    found.b_only_entity, _ = await add_findings(session_factory, found.b_chunks[0], "Lisbon")
    await add_findings(session_factory, legacy_chunk)
    return found


async def test_list_counts_only_the_organization(
    auth_client: httpx.AsyncClient, world: World
) -> None:
    a, b = world.tenants.a, world.tenants.b

    as_a = await auth_client.get(f"/entities?{a.query}", headers=a.headers["viewer"])
    as_b = await auth_client.get(f"/entities?{b.query}", headers=b.headers["viewer"])
    legacy = await auth_client.get("/entities", headers=world.tenants.system)

    assert [(item["canonical_name"], item["mention_count"]) for item in as_a.json()["items"]] == [
        ("Porto", 1)
    ]
    assert as_a.json()["total"] == 1
    assert "Lisbon" not in as_a.text
    assert [(item["canonical_name"], item["mention_count"]) for item in as_b.json()["items"]] == [
        ("Lisbon", 1),
        ("Porto", 3),
    ]
    assert [(item["canonical_name"], item["mention_count"]) for item in legacy.json()["items"]] == [
        ("Porto", 1)
    ]


async def test_filters_and_pages_stay_inside(auth_client: httpx.AsyncClient, world: World) -> None:
    a, b = world.tenants.a, world.tenants.b

    by_name = await auth_client.get(f"/entities?query=lis&{a.query}", headers=a.headers["owner"])
    by_type = await auth_client.get(
        f"/entities?entity_type=city&{b.query}", headers=b.headers["owner"]
    )
    second = await auth_client.get(
        f"/entities?limit=1&offset=1&{b.query}", headers=b.headers["owner"]
    )

    assert by_name.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
    assert by_type.json()["total"] == 2
    assert [item["canonical_name"] for item in second.json()["items"]] == ["Porto"]
    assert second.json()["total"] == 2


async def test_detail_shows_only_the_organization(
    auth_client: httpx.AsyncClient, world: World
) -> None:
    a = world.tenants.a
    path = f"/entities/{world.shared_entity}"

    detail = await auth_client.get(f"{path}?{a.query}", headers=a.headers["member"])
    b_only = await auth_client.get(
        f"/entities/{world.b_only_entity}?{a.query}", headers=a.headers["member"]
    )
    missing = await auth_client.get(path, headers=a.headers["member"])

    body = detail.json()
    assert (body["mention_count"], body["entity"]["mention_count"]) == (1, 1)
    assert [mention["chunk_id"] for mention in body["mentions"]] == [str(world.a_chunk)]
    for chunk in world.b_chunks:
        assert str(chunk) not in detail.text
    assert (b_only.status_code, missing.status_code) == (404, 422)


async def test_auth_disabled_lists_everything(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await add_source(session_factory, None)
    _, [chunk] = await add_document(session_factory, source, "doc", ["Porto."])
    entity, _ = await add_findings(session_factory, chunk)

    listed = await client.get("/entities")
    detail = await client.get(f"/entities/{entity}")

    assert listed.json()["items"][0]["mention_count"] == 1
    assert detail.json()["mention_count"] == 1
