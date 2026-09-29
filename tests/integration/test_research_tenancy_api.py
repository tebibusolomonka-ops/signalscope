import dataclasses
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fake_answers import FakeAnswerGenerator
from password_helpers import fast_hasher
from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.core.settings import Settings
from tenancy_helpers import Tenants, add_document, add_source, make_tenants

pytestmark = pytest.mark.anyio

QUERY = {"query": "harbour flood", "mode": "lexical", "limit": 5}


@pytest.fixture
def generator() -> FakeAnswerGenerator:
    return FakeAnswerGenerator()


@pytest.fixture
async def tenant_client(
    database_engine: AsyncEngine, migrated_database: Settings, generator: FakeAnswerGenerator
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(dataclasses.replace(migrated_database, auth_enabled=True))
    app.state.password_hasher = fast_hasher()
    app.state.answer_generators.register(generator)
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
async def tenants(
    tenant_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> Tenants:
    found = await make_tenants(tenant_client, session_factory)
    a_source = await add_source(session_factory, found.a.id, "a feed")
    b_source = await add_source(session_factory, found.b.id, "b feed")
    await add_document(session_factory, a_source, "a-doc", ["Harbour flood near the A dock."])
    # More and stronger matches in B, which must never be used for A.
    await add_document(
        session_factory, b_source, "b-doc", ["Harbour flood, harbour flood, bravo."] * 10
    )
    return found


async def test_context_uses_one_organization(
    tenant_client: httpx.AsyncClient, tenants: Tenants
) -> None:
    a = tenants.a

    response = await tenant_client.post(
        "/research/context",
        json=QUERY | {"organization_id": str(a.id)},
        headers=a.headers["viewer"],
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["title"] for item in body["evidence"]] == ["a-doc"]
    assert "bravo" not in body["context_text"] and "b-doc" not in response.text


async def test_answer_model_sees_one_organization(
    tenant_client: httpx.AsyncClient, tenants: Tenants, generator: FakeAnswerGenerator
) -> None:
    b = tenants.b

    response = await tenant_client.post(
        "/research/answer", json=QUERY | {"organization_id": str(b.id)}, headers=b.headers["viewer"]
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert {item["title"] for item in body["citations"]} == {"b-doc"}
    [request] = generator.requests
    assert {item.title for item in request.evidence} == {"b-doc"}
    assert all("A dock" not in item.text for item in request.evidence)


async def test_errors_and_legacy(tenant_client: httpx.AsyncClient, tenants: Tenants) -> None:
    a, b = tenants.a, tenants.b
    b_sources = await tenant_client.get(f"/sources?{b.query}", headers=b.headers["viewer"])
    b_source = b_sources.json()["items"][0]["id"]

    missing = await tenant_client.post("/research/context", json=QUERY, headers=a.headers["viewer"])
    other = await tenant_client.post(
        "/research/context",
        json=QUERY | {"organization_id": str(b.id)},
        headers=a.headers["viewer"],
    )
    wrong_source = await tenant_client.post(
        "/research/answer",
        json=QUERY | {"organization_id": str(a.id), "source_id": b_source},
        headers=a.headers["viewer"],
    )
    legacy = await tenant_client.post("/research/context", json=QUERY, headers=tenants.system)

    assert (missing.status_code, other.status_code, wrong_source.status_code) == (422, 404, 404)
    assert legacy.json()["evidence"] == []


async def test_auth_disabled_searches_everything(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await add_source(session_factory, None)
    await add_document(session_factory, source, "doc", ["Harbour flood."])

    response = await client.post("/research/context", json=QUERY)

    assert [item["title"] for item in response.json()["evidence"]] == ["doc"]
