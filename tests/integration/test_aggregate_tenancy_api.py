import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import report_event
from signalscope.domain.events.linking import EventLinkingService
from signalscope.domain.search.embedding_job import EmbeddingJob
from signalscope.domain.sources.scheduling import utc_now
from tenancy_helpers import Tenants, add_document, add_findings, add_source, make_tenants

pytestmark = pytest.mark.anyio


class World:
    tenants: Tenants
    a_source: uuid.UUID
    a_other: uuid.UUID
    b_source: uuid.UUID


@pytest.fixture
async def world(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> World:
    """A has two sources, B has one. Both report the same event today."""
    found = World()
    found.tenants = await make_tenants(auth_client, session_factory)
    found.a_source = await add_source(session_factory, found.tenants.a.id, "a feed")
    found.a_other = await add_source(session_factory, found.tenants.a.id, "a other")
    found.b_source = await add_source(session_factory, found.tenants.b.id, "b feed")
    _, [a_chunk] = await add_document(session_factory, found.a_source, "a-doc", ["Porto a."])
    _, b_chunks = await add_document(session_factory, found.b_source, "b-doc", ["Porto b."] * 3)
    await add_findings(session_factory, a_chunk)
    for chunk in b_chunks:
        await add_findings(session_factory, chunk)
    today = utc_now()
    await report_event(session_factory, found.a_source, "Harbour flood", occurred_at=today)
    await report_event(session_factory, found.b_source, "Harbour flood", occurred_at=today)
    await report_event(session_factory, found.b_source, "Bridge closed", occurred_at=today)
    await EventLinkingService(session_factory).link_unclustered()
    async with session_factory() as session:
        session.add_all(EmbeddingJob(chunk_id=chunk, provider="p", model="m") for chunk in b_chunks)
        await session.commit()
    return found


async def test_provenance(auth_client: httpx.AsyncClient, world: World) -> None:
    a = world.tenants.a

    own = await auth_client.get(
        f"/sources/{world.a_source}/provenance", headers=a.headers["viewer"]
    )
    other = await auth_client.get(
        f"/sources/{world.b_source}/provenance", headers=a.headers["viewer"]
    )

    body = own.json()
    assert (body["document_count"], body["entity_count"], body["claim_count"]) == (2, 1, 1)
    assert (body["event_count"], body["event_cluster_count"]) == (1, 1)
    # The cluster also holds B's event, but B's source does not count here.
    assert body["cross_source_event_cluster_count"] == 0
    assert other.status_code == 404


async def test_comparison(auth_client: httpx.AsyncClient, world: World) -> None:
    a = world.tenants.a
    body = {"source_ids": [str(world.a_source), str(world.a_other)], "organization_id": str(a.id)}

    same = await auth_client.post("/sources/compare", json=body, headers=a.headers["viewer"])
    across = await auth_client.post(
        "/sources/compare",
        json=body | {"source_ids": [str(world.a_source), str(world.b_source)]},
        headers=a.headers["owner"],
    )
    by_system = await auth_client.post(
        "/sources/compare",
        json=body | {"source_ids": [str(world.a_source), str(world.b_source)]},
        headers=world.tenants.system,
    )
    missing = await auth_client.post(
        "/sources/compare", json={"source_ids": body["source_ids"]}, headers=a.headers["owner"]
    )

    assert same.status_code == 200, same.text
    assert same.json()["shared_event_cluster_count"] == 0
    assert (across.status_code, by_system.status_code, missing.status_code) == (404, 404, 422)
    assert "b feed" not in across.text


async def test_dashboard_overview(auth_client: httpx.AsyncClient, world: World) -> None:
    a, b = world.tenants.a, world.tenants.b

    as_a = (
        await auth_client.get(f"/dashboard/overview?{a.query}", headers=a.headers["viewer"])
    ).json()
    as_b = (
        await auth_client.get(f"/dashboard/overview?{b.query}", headers=b.headers["viewer"])
    ).json()
    legacy = (await auth_client.get("/dashboard/overview", headers=world.tenants.system)).json()

    assert {key: as_a[key] for key in ("sources", "documents", "chunks", "entities", "claims")} == {
        "sources": 2,
        "documents": 2,
        "chunks": 2,
        "entities": 1,
        "claims": 1,
    }
    assert (as_a["events"], as_a["event_clusters"], as_a["pending_embeddings"]) == (1, 1, 0)
    assert (as_b["sources"], as_b["documents"], as_b["chunks"]) == (1, 3, 5)
    assert (as_b["events"], as_b["event_clusters"], as_b["pending_embeddings"]) == (2, 2, 3)
    assert all(value == 0 for value in legacy.values())


async def test_dashboard_activity(auth_client: httpx.AsyncClient, world: World) -> None:
    a, b = world.tenants.a, world.tenants.b

    a_sources = await auth_client.get(
        f"/dashboard/sources?days=1&{a.query}", headers=a.headers["viewer"]
    )
    a_events = await auth_client.get(
        f"/dashboard/events?days=1&{a.query}", headers=a.headers["viewer"]
    )
    b_events = await auth_client.get(
        f"/dashboard/events?days=1&{b.query}", headers=b.headers["viewer"]
    )
    other_source = await auth_client.get(
        f"/dashboard/sources?{a.query}&source_id={world.b_source}", headers=a.headers["viewer"]
    )

    assert a_sources.json()["items"][-1]["documents_created"] == 2
    [a_day] = a_events.json()["items"]
    [b_day] = b_events.json()["items"]
    # The shared cluster has two sources overall, but one in each organization.
    assert (a_day["events"], a_day["clusters"], a_day["cross_source_clusters"]) == (1, 1, 0)
    assert (b_day["events"], b_day["clusters"], b_day["cross_source_clusters"]) == (2, 2, 0)
    assert other_source.status_code == 404


async def test_auth_disabled_counts_everything(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    first = await add_source(session_factory, None)
    second = await add_source(session_factory, None)
    today = datetime.now(UTC)
    await report_event(session_factory, first, "Harbour flood", occurred_at=today)
    await report_event(session_factory, second, "Harbour flood", occurred_at=today)
    await EventLinkingService(session_factory).link_unclustered()

    overview = (await client.get("/dashboard/overview")).json()
    [day] = (await client.get("/dashboard/events?days=1")).json()["items"]
    provenance = (await client.get(f"/sources/{first}/provenance")).json()

    assert (overview["sources"], overview["events"], overview["event_clusters"]) == (2, 2, 1)
    assert day["cross_source_clusters"] == 1
    assert provenance["cross_source_event_cluster_count"] == 1
