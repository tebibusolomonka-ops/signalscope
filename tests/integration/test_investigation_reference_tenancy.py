import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import report_event
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.events.cluster import EventClusterMember
from signalscope.domain.events.linking import EventLinkingService
from signalscope.domain.investigations.model import Investigation
from signalscope.domain.research.session import ResearchSession
from tenancy_helpers import Tenants, add_document, add_findings, add_source, make_tenants

pytestmark = pytest.mark.anyio

DAY = datetime(2026, 9, 1, 12, tzinfo=UTC)


async def records(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID | None, tag: str
) -> dict[str, str]:
    """One record of every savable type for the organization, by item type."""
    source = await add_source(session_factory, organization_id, f"{tag} feed")
    document, [chunk] = await add_document(session_factory, source, f"{tag}-doc", [f"Porto {tag}."])
    entity, claim = await add_findings(session_factory, chunk)
    event = await report_event(session_factory, source, f"Flood {tag}", occurred_at=DAY)
    await EventLinkingService(session_factory).link_unclustered()
    async with session_factory() as session:
        cluster = await session.scalar(
            select(EventClusterMember.cluster_id).where(EventClusterMember.event_id == event)
        )
        research = ResearchSession(title=f"{tag} session", organization_id=organization_id)
        session.add(research)
        await session.commit()
    return {
        "source": str(source),
        "document": str(document),
        "event": str(event),
        "event_cluster": str(cluster),
        "entity": str(entity),
        "claim": str(claim),
        "research_session": str(research.id),
    }


class World:
    tenants: Tenants
    a: dict[str, str]
    b: dict[str, str]
    legacy: dict[str, str]
    b_only_entity: str


@pytest.fixture
async def world(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> World:
    found = World()
    found.tenants = await make_tenants(auth_client, session_factory)
    found.a = await records(session_factory, found.tenants.a.id, "a")
    # B mentions the same entity and claim, and one entity of its own.
    found.b = await records(session_factory, found.tenants.b.id, "b")
    found.legacy = await records(session_factory, None, "legacy")
    async with session_factory() as session:
        chunk = await session.scalar(
            select(DocumentChunk.id).where(DocumentChunk.text == "Porto b.")
        )
    assert chunk is not None
    entity, _ = await add_findings(session_factory, chunk, "Lisbon", claim_text=None, start=4)
    found.b_only_entity = str(entity)
    return found


async def investigation(
    client: httpx.AsyncClient, headers: dict[str, str], organization_id: uuid.UUID
) -> str:
    response = await client.post(
        "/investigations",
        json={"title": "Floods", "organization_id": str(organization_id)},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return f"/investigations/{response.json()['id']}"


async def save(
    client: httpx.AsyncClient, path: str, headers: dict[str, str], item_type: str, reference: str
) -> httpx.Response:
    return await client.post(
        f"{path}/items", json={"item_type": item_type, "reference_id": reference}, headers=headers
    )


async def test_own_records_can_be_saved(auth_client: httpx.AsyncClient, world: World) -> None:
    a = world.tenants.a
    path = await investigation(auth_client, a.headers["member"], a.id)

    for item_type, reference in world.a.items():
        response = await save(auth_client, path, a.headers["member"], item_type, reference)
        assert response.status_code == 201, (item_type, response.text)
    exported = await auth_client.get(f"{path}/export", headers=a.headers["viewer"])
    assert "b-doc" not in exported.text and "b feed" not in exported.text


async def test_other_records_cannot_be_saved(auth_client: httpx.AsyncClient, world: World) -> None:
    a = world.tenants.a
    path = await investigation(auth_client, a.headers["member"], a.id)
    shared = {"entity", "claim"}

    for item_type, reference in world.b.items():
        response = await save(auth_client, path, a.headers["member"], item_type, reference)
        if item_type in shared:
            # The same shared row, backed by A's own evidence too.
            assert response.status_code == 201, item_type
        else:
            assert response.status_code == 404, item_type
            assert "was not found" in response.json()["error"]["message"]
    b_only = await save(auth_client, path, a.headers["member"], "entity", world.b_only_entity)
    assert b_only.status_code == 404
    for item_type, reference in world.legacy.items():
        if item_type in shared:
            continue
        response = await save(auth_client, path, a.headers["owner"], item_type, reference)
        assert response.status_code == 404, item_type


async def test_legacy_investigations_take_legacy_records(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    world: World,
) -> None:
    async with session_factory() as session:
        legacy = Investigation(title="Old")
        session.add(legacy)
        await session.commit()
    path = f"/investigations/{legacy.id}"
    system = world.tenants.system

    own = await save(auth_client, path, system, "document", world.legacy["document"])
    tenant = await save(auth_client, path, system, "document", world.a["document"])
    session_item = await save(
        auth_client, path, system, "research_session", world.legacy["research_session"]
    )

    assert (own.status_code, tenant.status_code, session_item.status_code) == (201, 404, 201)
