import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.research.session import ResearchSession
from tenancy_helpers import Tenants, add_document, add_source, make_tenants

pytestmark = pytest.mark.anyio

QUESTION = {"question": "harbour flood", "limit": 5}


class World:
    tenants: Tenants
    a_source: uuid.UUID
    b_source: uuid.UUID


@pytest.fixture
async def world(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> World:
    found = World()
    found.tenants = await make_tenants(auth_client, session_factory)
    found.a_source = await add_source(session_factory, found.tenants.a.id, "a feed")
    found.b_source = await add_source(session_factory, found.tenants.b.id, "b feed")
    await add_document(session_factory, found.a_source, "a-doc", ["Harbour flood in A."])
    await add_document(session_factory, found.b_source, "b-doc", ["Harbour flood in B bravo."] * 5)
    return found


async def create(
    client: httpx.AsyncClient, headers: dict[str, str], **body: object
) -> httpx.Response:
    return await client.post(
        "/research/sessions", json={"retrieval_mode": "lexical"} | body, headers=headers
    )


async def test_create_and_use_a_session(auth_client: httpx.AsyncClient, world: World) -> None:
    a = world.tenants.a
    organization = str(a.id)

    by_viewer = await create(auth_client, a.headers["viewer"], organization_id=organization)
    created = await create(auth_client, a.headers["member"], organization_id=organization)

    assert by_viewer.status_code == 403
    assert created.status_code == 201, created.text
    assert created.json()["organization_id"] == organization
    path = f"/research/sessions/{created.json()['id']}"
    viewer_turn = await auth_client.post(
        f"{path}/turns", json=QUESTION, headers=a.headers["viewer"]
    )
    turn = await auth_client.post(f"{path}/turns", json=QUESTION, headers=a.headers["member"])

    assert viewer_turn.status_code == 403
    assert turn.status_code == 201, turn.text
    titles = {item["title"] for item in turn.json()["turn"]["evidence"]}
    assert titles == {"a-doc"}
    assert "bravo" not in turn.text
    for suffix in ("", "/turns", "/export"):
        response = await auth_client.get(f"{path}{suffix}", headers=a.headers["viewer"])
        assert response.status_code == 200, suffix
        assert "bravo" not in response.text


async def test_other_organizations_and_sources(
    auth_client: httpx.AsyncClient, world: World
) -> None:
    a, b = world.tenants.a, world.tenants.b
    created = await create(auth_client, a.headers["member"], organization_id=str(a.id))
    path = f"/research/sessions/{created.json()['id']}"

    for method, suffix in (("GET", ""), ("GET", "/turns"), ("GET", "/export"), ("POST", "/turns")):
        response = await auth_client.request(
            method,
            f"{path}{suffix}",
            json=QUESTION if method == "POST" else None,
            headers=b.headers["owner"],
        )
        assert response.status_code == 404, (method, suffix)
    b_source = await create(
        auth_client, a.headers["member"], organization_id=str(a.id), source_id=str(world.b_source)
    )
    mismatch = await create(
        auth_client, world.tenants.system, organization_id=str(a.id), source_id=str(world.b_source)
    )
    missing = await create(auth_client, a.headers["member"])
    other = await create(auth_client, a.headers["member"], organization_id=str(b.id))

    assert (b_source.status_code, mismatch.status_code) == (404, 422)
    assert (missing.status_code, other.status_code) == (422, 404)


async def test_legacy_sessions(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    world: World,
) -> None:
    async with session_factory() as session:
        legacy = ResearchSession(title="Old")
        session.add(legacy)
        await session.commit()
    path = f"/research/sessions/{legacy.id}"

    by_owner = await auth_client.get(path, headers=world.tenants.a.headers["owner"])
    by_system = await auth_client.get(path, headers=world.tenants.system)

    assert (by_owner.status_code, by_system.status_code) == (404, 200)
    assert by_system.json()["organization_id"] is None


async def test_auth_disabled_sessions(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await add_source(session_factory, None)
    await add_document(session_factory, source, "doc", ["Harbour flood."])

    created = await client.post("/research/sessions", json={"retrieval_mode": "lexical"})
    turn = await client.post(f"/research/sessions/{created.json()['id']}/turns", json=QUESTION)
    with_organization = await client.post(
        "/research/sessions", json={"organization_id": str(uuid.uuid4())}
    )

    assert created.json()["organization_id"] is None
    assert [item["title"] for item in turn.json()["turn"]["evidence"]] == ["doc"]
    assert with_organization.status_code == 422
