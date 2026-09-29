"""A cross-organization leak audit over every content route.

Organizations A and B hold nearly the same content: the same words, entity,
claim and event title. Each has a marker word and its own IDs. A user of one
organization must never see the other's markers, IDs, titles or URLs, and
counts must not include the other's rows.
"""

import dataclasses
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from event_reports import report_event
from fake_answers import FakeAnswerGenerator
from fake_embeddings import FakeEmbeddingProvider
from fake_reranker import FakeReranker
from password_helpers import fast_hasher
from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.core.settings import Settings
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.events.cluster import EventClusterMember
from signalscope.domain.events.linking import EventLinkingService
from signalscope.domain.search.embedding_repository import ChunkEmbeddingRepository
from tenancy_helpers import Tenant, Tenants, add_document, add_findings, add_source, make_tenants

pytestmark = pytest.mark.anyio

E5 = ("sentence_transformers", "intfloat/multilingual-e5-small")
RERANKER = ("sentence_transformers", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
DAY = datetime(2026, 9, 1, 12, tzinfo=UTC)
SEMANTIC = f"provider={E5[0]}&model={E5[1]}"


@pytest.fixture
async def client(
    database_engine: AsyncEngine, migrated_database: Settings
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(dataclasses.replace(migrated_database, auth_enabled=True))
    app.state.password_hasher = fast_hasher()
    app.state.embedding_providers.register(FakeEmbeddingProvider(*E5))
    app.state.rerankers.register(FakeReranker(*RERANKER))
    app.state.answer_generators.register(FakeAnswerGenerator())
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@dataclasses.dataclass
class Content:
    """The IDs and markers of one organization's content."""

    tag: str
    marker: str
    source: str = ""
    other_source: str = ""
    document: str = ""
    chunks: list[str] = dataclasses.field(default_factory=list)
    event: str = ""
    cluster: str = ""
    entity: str = ""
    claim: str = ""

    @property
    def sentinels(self) -> list[str]:
        """Strings that only this organization's content contains."""
        ids = [self.source, self.other_source, self.document, *self.chunks, self.event]
        names = [f"{self.tag}-feed", f"{self.tag}-wire", f"{self.tag}-doc"]
        return [self.marker, self.marker.lower(), *names, *ids, self.cluster]


async def build(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID | None,
    tag: str,
    chunk_count: int,
) -> Content:
    content = Content(tag=tag, marker=f"{tag.upper()}MARKER")
    source = await add_source(session_factory, organization_id, f"{tag}-feed")
    other = await add_source(session_factory, organization_id, f"{tag}-wire")
    text = f"Harbour flood near Porto, water rose. {content.marker}"
    document, chunks = await add_document(
        session_factory, source, f"{tag}-doc", [f"{text} {index}" for index in range(chunk_count)]
    )
    embedder = FakeEmbeddingProvider(*E5)
    async with session_factory() as session:
        for chunk_id in chunks:
            chunk = await session.get_one(DocumentChunk, chunk_id)
            await ChunkEmbeddingRepository(session).save(
                chunk.id, *E5, chunk.text_hash, embedder.vector(chunk.text)
            )
        await session.commit()
    for chunk in chunks:
        entity, claim = await add_findings(session_factory, chunk)
    event = await report_event(session_factory, source, "Harbour flood", occurred_at=DAY)
    await EventLinkingService(session_factory).link_unclustered()
    async with session_factory() as session:
        cluster = await session.scalar(
            select(EventClusterMember.cluster_id).where(EventClusterMember.event_id == event)
        )
    content.source, content.other_source, content.document = str(source), str(other), str(document)
    content.chunks = [str(chunk) for chunk in chunks]
    content.event, content.cluster = str(event), str(cluster)
    content.entity, content.claim = str(entity), str(claim)
    return content


class World:
    tenants: Tenants
    a: Content
    b: Content
    legacy: Content


@pytest.fixture
async def world(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> World:
    found = World()
    found.tenants = await make_tenants(client, session_factory)
    found.a = await build(session_factory, found.tenants.a.id, "alpha", 1)
    found.b = await build(session_factory, found.tenants.b.id, "bravo", 3)
    found.legacy = await build(session_factory, None, "legacy", 2)
    return found


def assert_hidden(response: httpx.Response, hidden: list[str], name: str) -> None:
    """The response body contains none of the hidden strings. Only the name is reported."""
    assert response.status_code < 300, (name, response.status_code)
    body = response.text
    leaked = [index for index, secret in enumerate(hidden) if secret and secret in body]
    assert not leaked, f"{name} shows another organization's content"


async def visit(
    client: httpx.AsyncClient, tenant: Tenant, own: Content
) -> dict[str, httpx.Response]:
    """Every content route, for one organization's viewer or member."""
    q = tenant.query
    viewer, member = tenant.headers["viewer"], tenant.headers["member"]
    research: dict[str, Any] = {"query": "harbour flood", "mode": "hybrid", "limit": 5}
    research["organization_id"] = str(tenant.id)
    responses = {
        "sources": await client.get(f"/sources?{q}", headers=viewer),
        "source": await client.get(f"/sources/{own.source}", headers=viewer),
        "provenance": await client.get(f"/sources/{own.source}/provenance", headers=viewer),
        "compare": await client.post(
            "/sources/compare",
            json={"source_ids": [own.source, own.other_source], "organization_id": str(tenant.id)},
            headers=viewer,
        ),
        "runs": await client.get(f"/ingestion-runs?{q}", headers=viewer),
        "documents": await client.get(f"/documents?{q}", headers=viewer),
        "document": await client.get(f"/documents/{own.document}", headers=viewer),
        "revisions": await client.get(f"/documents/{own.document}/revisions", headers=viewer),
        "search": await client.get(f"/search?q=harbour&limit=50&{q}", headers=viewer),
        "semantic": await client.get(
            f"/search/semantic?q=water&limit=50&{SEMANTIC}&{q}", headers=viewer
        ),
        "hybrid": await client.get(
            f"/search/hybrid?q=harbour water&limit=50&{SEMANTIC}&{q}", headers=viewer
        ),
        "reranked": await client.get(f"/search/reranked?q=harbour&limit=20&{q}", headers=viewer),
        "entities": await client.get(f"/entities?{q}", headers=viewer),
        "entity": await client.get(f"/entities/{own.entity}?{q}", headers=viewer),
        "claims": await client.get(f"/claims?{q}", headers=viewer),
        "claim": await client.get(f"/claims/{own.claim}?{q}", headers=viewer),
        "events": await client.get(f"/events?{q}", headers=viewer),
        "event": await client.get(f"/events/{own.event}?{q}", headers=viewer),
        "suggestions": await client.get(
            f"/events/{own.event}/link-suggestions?{q}", headers=viewer
        ),
        "cluster": await client.get(f"/event-clusters/{own.cluster}?{q}", headers=viewer),
        "timeline": await client.get(f"/timeline?{q}", headers=viewer),
        "overview": await client.get(f"/dashboard/overview?{q}", headers=viewer),
        "source activity": await client.get(f"/dashboard/sources?{q}", headers=viewer),
        "event activity": await client.get(f"/dashboard/events?{q}", headers=viewer),
        "context": await client.post("/research/context", json=research, headers=viewer),
        "answer": await client.post("/research/answer", json=research, headers=viewer),
    }
    for path in ("embeddings", "entities", "events", "claims"):
        responses[f"{path} coverage"] = await client.get(f"/{path}/coverage?{q}", headers=viewer)
    session = await client.post(
        "/research/sessions",
        json={"organization_id": str(tenant.id), "retrieval_mode": "lexical"},
        headers=member,
    )
    session_path = f"/research/sessions/{session.json()['id']}"
    responses["research turn"] = await client.post(
        f"{session_path}/turns", json={"question": "harbour flood"}, headers=member
    )
    responses["research export"] = await client.get(f"{session_path}/export", headers=viewer)
    investigation = await client.post(
        "/investigations",
        json={"title": "Floods", "organization_id": str(tenant.id)},
        headers=member,
    )
    items = f"/investigations/{investigation.json()['id']}/items"
    for item_type, reference in (
        ("document", own.document),
        ("entity", own.entity),
        ("claim", own.claim),
        ("event_cluster", own.cluster),
    ):
        responses[f"save {item_type}"] = await client.post(
            items, json={"item_type": item_type, "reference_id": reference}, headers=member
        )
    responses["investigation export"] = await client.get(
        items.replace("/items", "/export"), headers=viewer
    )
    return responses


@pytest.mark.parametrize("side", ["a", "b"])
async def test_no_route_shows_the_other_organization(
    client: httpx.AsyncClient, world: World, side: str
) -> None:
    tenant, own, other = (
        (world.tenants.a, world.a, world.b) if side == "a" else (world.tenants.b, world.b, world.a)
    )
    hidden = [*other.sentinels, *world.legacy.sentinels]

    responses = await visit(client, tenant, own)

    for name, response in responses.items():
        assert_hidden(response, hidden, name)
    assert own.marker in responses["search"].text
    own_chunks = len(own.chunks)
    entity = responses["entity"].json()
    assert entity["mention_count"] == own_chunks
    assert responses["claim"].json()["evidence_count"] == own_chunks
    overview = responses["overview"].json()
    assert (overview["sources"], overview["documents"]) == (2, 2)
    assert overview["chunks"] == own_chunks + 1
    assert (overview["entities"], overview["claims"], overview["events"]) == (1, 1, 1)
    assert overview["event_clusters"] == 1
    # Its document chunks and the chunk its event was found in.
    assert len(responses["search"].json()["items"]) == own_chunks + 1
    assert responses["timeline"].json()["items"][0]["evidence_count"] == 1
    assert responses["suggestions"].json() == []


async def test_direct_ids_of_the_other_organization_are_not_found(
    client: httpx.AsyncClient, world: World
) -> None:
    a, other = world.tenants.a, world.b
    viewer = a.headers["owner"]
    q = a.query
    paths = [
        f"/sources/{other.source}",
        f"/sources/{other.source}/provenance",
        f"/documents/{other.document}",
        f"/documents/{other.document}/revisions",
        f"/events/{other.event}?{q}",
        f"/events/{other.event}/link-suggestions?{q}",
        f"/event-clusters/{other.cluster}?{q}",
        f"/entities/coverage?document_id={other.document}",
        f"/documents?source_id={other.source}&{q}",
        f"/search?q=harbour&source_id={other.source}&{q}",
        f"/sources?{world.tenants.b.query}",
    ]
    for path in paths:
        response = await client.get(path, headers=viewer)
        assert response.status_code == 404, path
        assert not any(secret in response.text for secret in other.sentinels), path


async def test_system_admin_picks_one_organization_at_a_time(
    client: httpx.AsyncClient, world: World
) -> None:
    system = world.tenants.system

    as_a = await client.get(f"/search?q=harbour&limit=50&{world.tenants.a.query}", headers=system)
    as_b = await client.get(f"/search?q=harbour&limit=50&{world.tenants.b.query}", headers=system)
    no_organization = await client.get("/search?q=harbour&limit=50", headers=system)
    overview = await client.get("/dashboard/overview", headers=system)

    assert_hidden(as_a, [*world.b.sentinels, *world.legacy.sentinels], "system as A")
    assert_hidden(as_b, [*world.a.sentinels, *world.legacy.sentinels], "system as B")
    # Without an organization only legacy content, never A and B together.
    assert_hidden(no_organization, [*world.a.sentinels, *world.b.sentinels], "system legacy")
    assert world.legacy.marker in no_organization.text
    assert overview.json()["chunks"] == len(world.legacy.chunks) + 1


async def test_normal_users_cannot_reach_legacy_content(
    client: httpx.AsyncClient, world: World
) -> None:
    owner = world.tenants.a.headers["owner"]

    no_organization = await client.get("/search?q=harbour", headers=owner)
    legacy_source = await client.get(f"/sources/{world.legacy.source}", headers=owner)
    legacy_document = await client.get(f"/documents/{world.legacy.document}", headers=owner)

    assert no_organization.status_code == 422
    assert (legacy_source.status_code, legacy_document.status_code) == (404, 404)
    assert world.legacy.marker not in json.dumps([legacy_source.text, legacy_document.text])
