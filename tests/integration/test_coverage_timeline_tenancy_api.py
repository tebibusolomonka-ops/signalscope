from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import report_event
from signalscope.domain.events.linking import EventLinkingService
from tenancy_helpers import Tenants, add_document, add_source, make_tenants

pytestmark = pytest.mark.anyio

DAY = datetime(2026, 9, 1, 12, tzinfo=UTC)
COVERAGE = ["/embeddings/coverage", "/entities/coverage", "/events/coverage", "/claims/coverage"]


class World:
    tenants: Tenants
    a_document: str
    b_document: str


@pytest.fixture
async def world(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> World:
    found = World()
    found.tenants = await make_tenants(auth_client, session_factory)
    a_source = await add_source(session_factory, found.tenants.a.id, "a feed")
    b_source = await add_source(session_factory, found.tenants.b.id, "b feed")
    a_document, _ = await add_document(session_factory, a_source, "a-doc", ["One.", "Two."])
    b_document, _ = await add_document(session_factory, b_source, "b-doc", ["1.", "2.", "3."])
    found.a_document, found.b_document = str(a_document), str(b_document)
    # Each report_event adds a document with one chunk per evidence row.
    await report_event(session_factory, a_source, "Harbour flood", occurred_at=DAY)
    await report_event(
        session_factory, b_source, "Harbour flood", occurred_at=DAY, evidence_count=2
    )
    await report_event(session_factory, b_source, "Bridge closed", occurred_at=DAY)
    async with session_factory() as session:
        await EventLinkingService(session).link_unclustered()
        await session.commit()
    return found


@pytest.mark.parametrize("path", COVERAGE)
async def test_coverage_counts_one_organization(
    auth_client: httpx.AsyncClient, world: World, path: str
) -> None:
    a, b = world.tenants.a, world.tenants.b

    as_a = await auth_client.get(f"{path}?{a.query}", headers=a.headers["viewer"])
    as_b = await auth_client.get(f"{path}?{b.query}", headers=b.headers["viewer"])
    legacy = await auth_client.get(path, headers=world.tenants.system)
    own_document = await auth_client.get(
        f"{path}?document_id={world.a_document}", headers=a.headers["viewer"]
    )
    other_document = await auth_client.get(
        f"{path}?document_id={world.b_document}", headers=a.headers["viewer"]
    )
    missing = await auth_client.get(path, headers=a.headers["viewer"])

    # A: 2 chunks plus 1 event chunk. B: 3 chunks plus 2 and 1 event chunks.
    assert as_a.json()["chunk_count"] == 3
    assert as_b.json()["chunk_count"] == 6
    assert legacy.json()["chunk_count"] == 0
    assert own_document.json()["chunk_count"] == 2
    assert (other_document.status_code, missing.status_code) == (404, 422)


async def test_timeline_counts_one_organization(
    auth_client: httpx.AsyncClient, world: World
) -> None:
    a, b = world.tenants.a, world.tenants.b

    as_a = await auth_client.get(f"/timeline?{a.query}", headers=a.headers["viewer"])
    as_b = await auth_client.get(f"/timeline?{b.query}", headers=b.headers["viewer"])

    [item] = as_a.json()["items"]
    assert as_a.json()["total"] == 1
    assert (item["title"], item["event_count"], item["source_count"]) == ("Harbour flood", 1, 1)
    assert item["evidence_count"] == 1
    assert [source["name"] for source in item["sources"]] == ["a feed"]
    assert "b feed" not in as_a.text and "Bridge closed" not in as_a.text
    by_title = {entry["title"]: entry for entry in as_b.json()["items"]}
    assert set(by_title) == {"Harbour flood", "Bridge closed"}
    assert (
        by_title["Harbour flood"]["event_count"],
        by_title["Harbour flood"]["evidence_count"],
    ) == (
        1,
        2,
    )


async def test_timeline_source_filter(auth_client: httpx.AsyncClient, world: World) -> None:
    a = world.tenants.a
    b_source = await auth_client.get(
        f"/sources?{world.tenants.b.query}", headers=world.tenants.b.headers["viewer"]
    )
    b_source_id = b_source.json()["items"][0]["id"]

    response = await auth_client.get(
        f"/timeline?{a.query}&source_id={b_source_id}", headers=a.headers["owner"]
    )

    assert response.status_code == 404


async def test_auth_disabled_counts_everything(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await add_source(session_factory, None)
    await add_document(session_factory, source, "doc", ["One.", "Two."])

    for path in COVERAGE:
        assert (await client.get(path)).json()["chunk_count"] == 2
    assert (await client.get("/timeline")).json()["total"] == 0
