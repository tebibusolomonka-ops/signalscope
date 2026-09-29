import dataclasses
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from event_reports import report_event
from fake_embeddings import FakeEmbeddingProvider
from password_helpers import fast_hasher
from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.core.settings import Settings
from signalscope.domain.events.cluster import EventClusterMember
from signalscope.domain.events.linking import EventLinkingService
from tenancy_helpers import Tenants, add_document, add_findings, add_source, make_tenants

pytestmark = pytest.mark.anyio

DAY = datetime(2026, 9, 1, 12, tzinfo=UTC)


@pytest.fixture
def embedder() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider("sentence_transformers", "intfloat/multilingual-e5-small")


@pytest.fixture
async def tenant_client(
    database_engine: AsyncEngine, migrated_database: Settings, embedder: FakeEmbeddingProvider
) -> AsyncIterator[httpx.AsyncClient]:
    """Auth on, with a fake E5 model for link suggestions."""
    app = create_app(dataclasses.replace(migrated_database, auth_enabled=True))
    app.state.password_hasher = fast_hasher()
    app.state.embedding_providers.register(embedder)
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


class World:
    tenants: Tenants
    claim: uuid.UUID
    a_chunk: uuid.UUID
    b_chunks: list[uuid.UUID]
    a_event: uuid.UUID
    b_event: uuid.UUID
    b_only_event: uuid.UUID
    cluster: uuid.UUID


@pytest.fixture
async def world(
    tenant_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> World:
    found = World()
    found.tenants = await make_tenants(tenant_client, session_factory)
    a_source = await add_source(session_factory, found.tenants.a.id, "a feed")
    b_source = await add_source(session_factory, found.tenants.b.id, "b feed")
    _, [found.a_chunk] = await add_document(session_factory, a_source, "a-doc", ["Water rose a."])
    _, found.b_chunks = await add_document(
        session_factory, b_source, "b-doc", ["Water rose b."] * 2
    )
    _, found.claim = await add_findings(session_factory, found.a_chunk)
    for chunk in found.b_chunks:
        await add_findings(session_factory, chunk)
    # The same event title and day in both organizations. The linker from
    # before organizations puts them in one cluster.
    found.a_event = await report_event(session_factory, a_source, "Harbour flood", occurred_at=DAY)
    found.b_event = await report_event(
        session_factory, b_source, "Harbour flood", occurred_at=DAY, evidence_count=2
    )
    found.b_only_event = await report_event(
        session_factory, b_source, "Harbour flood warning", occurred_at=DAY
    )
    async with session_factory() as session:
        await EventLinkingService(session).link_unclustered()
        await session.commit()
        cluster = await session.scalar(
            select(EventClusterMember.cluster_id).where(
                EventClusterMember.event_id == found.a_event
            )
        )
        assert cluster is not None
        found.cluster = cluster
    return found


async def test_claims(tenant_client: httpx.AsyncClient, world: World) -> None:
    a, b = world.tenants.a, world.tenants.b
    path = f"/claims/{world.claim}"

    listed = await tenant_client.get(f"/claims?{a.query}", headers=a.headers["viewer"])
    detail = await tenant_client.get(f"{path}?{a.query}", headers=a.headers["viewer"])
    as_b = await tenant_client.get(f"{path}?{b.query}", headers=b.headers["viewer"])

    assert [(item["text"], item["evidence_count"]) for item in listed.json()["items"]] == [
        ("Water rose", 1)
    ]
    assert detail.json()["evidence_count"] == 1
    assert [item["chunk_id"] for item in detail.json()["evidence"]] == [str(world.a_chunk)]
    for chunk in world.b_chunks:
        assert str(chunk) not in detail.text
    assert as_b.json()["evidence_count"] == 2


async def test_events(tenant_client: httpx.AsyncClient, world: World) -> None:
    a = world.tenants.a
    viewer = a.headers["viewer"]

    listed = await tenant_client.get(f"/events?{a.query}", headers=viewer)
    own = await tenant_client.get(f"/events/{world.a_event}?{a.query}", headers=viewer)
    other = await tenant_client.get(f"/events/{world.b_event}?{a.query}", headers=viewer)
    missing = await tenant_client.get(f"/events/{world.a_event}", headers=viewer)

    assert [item["id"] for item in listed.json()["items"]] == [str(world.a_event)]
    assert listed.json()["total"] == 1
    assert len(own.json()["evidence"]) == 1
    assert (other.status_code, missing.status_code) == (404, 422)


async def test_cluster_detail_hides_other_members(
    tenant_client: httpx.AsyncClient, world: World
) -> None:
    a, b = world.tenants.a, world.tenants.b
    path = f"/event-clusters/{world.cluster}"

    as_a = await tenant_client.get(f"{path}?{a.query}", headers=a.headers["viewer"])
    as_b = await tenant_client.get(f"{path}?{b.query}", headers=b.headers["viewer"])

    body = as_a.json()
    assert [member["event_id"] for member in body["members"]] == [str(world.a_event)]
    assert (body["event_count"], body["source_count"], body["evidence_count"]) == (1, 1, 1)
    assert "b feed" not in as_a.text and str(world.b_event) not in as_a.text
    assert [member["event_id"] for member in as_b.json()["members"]] == [str(world.b_event)]
    assert as_b.json()["evidence_count"] == 2


async def test_suggestions_stay_inside(
    tenant_client: httpx.AsyncClient, world: World, embedder: FakeEmbeddingProvider
) -> None:
    b = world.tenants.b
    path = f"/events/{world.b_only_event}/link-suggestions"

    own = await tenant_client.get(f"{path}?{b.query}", headers=b.headers["viewer"])
    other = await tenant_client.get(
        f"{path}?{world.tenants.a.query}", headers=world.tenants.a.headers["viewer"]
    )

    assert [item["candidate_event_id"] for item in own.json()] == [str(world.b_event)]
    assert other.status_code == 404
    # The event and its one candidate in B; nothing from A is embedded.
    assert [len(call) for call in embedder.calls] == [2]


async def test_auth_disabled_sees_all_evidence(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await add_source(session_factory, None)
    _, chunks = await add_document(session_factory, source, "doc", ["Water rose."] * 2)
    for chunk in chunks:
        _, claim = await add_findings(session_factory, chunk)
    event = await report_event(session_factory, source, "Harbour flood", occurred_at=DAY)

    claims = await client.get("/claims")
    detail = await client.get(f"/claims/{claim}")
    events = await client.get(f"/events/{event}")

    assert claims.json()["items"][0]["evidence_count"] == 2
    assert detail.json()["evidence_count"] == 2
    assert len(events.json()["evidence"]) == 1
