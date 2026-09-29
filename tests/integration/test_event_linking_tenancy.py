import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from event_reports import report_event
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.linking import EventLinkingService, EventOwnershipError
from signalscope.domain.events.model import Event, EventEvidence
from signalscope.domain.organizations.service import OrganizationService
from tenancy_helpers import add_document, add_source

pytestmark = pytest.mark.anyio

DAY = datetime(2026, 9, 1, 12, tzinfo=UTC)


async def organization(session_factory: async_sessionmaker[AsyncSession], slug: str) -> uuid.UUID:
    owner = await create_account(session_factory, f"{slug}@example.org")
    async with session_factory() as session:
        return (await OrganizationService(session).create(owner, slug.title(), slug)).id


async def cluster_of(
    session_factory: async_sessionmaker[AsyncSession], event_id: uuid.UUID
) -> EventCluster | None:
    async with session_factory() as session:
        return await session.scalar(
            select(EventCluster)
            .join(EventClusterMember, EventClusterMember.cluster_id == EventCluster.id)
            .where(EventClusterMember.event_id == event_id)
        )


async def test_clusters_stay_inside_organizations(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    harbour = await organization(session_factory, "harbour")
    river = await organization(session_factory, "river")
    sources = {
        "harbour 1": await add_source(session_factory, harbour),
        "harbour 2": await add_source(session_factory, harbour),
        "river": await add_source(session_factory, river),
        "legacy 1": await add_source(session_factory, None),
        "legacy 2": await add_source(session_factory, None),
    }
    events = {
        name: await report_event(session_factory, source, "Harbour flood", occurred_at=DAY)
        for name, source in sources.items()
    }

    result = await EventLinkingService(session_factory).link_unclustered()

    clusters = {name: await cluster_of(session_factory, event) for name, event in events.items()}
    assert result.events_linked == 5
    assert result.clusters_created == 3
    assert clusters["harbour 1"] is not None and clusters["river"] is not None
    assert clusters["legacy 1"] is not None
    assert clusters["harbour 1"].id == clusters["harbour 2"].id  # type: ignore[union-attr]
    assert clusters["harbour 1"].organization_id == harbour
    assert clusters["river"].organization_id == river
    assert clusters["river"].id != clusters["harbour 1"].id
    assert clusters["legacy 1"].id == clusters["legacy 2"].id  # type: ignore[union-attr]
    assert clusters["legacy 1"].organization_id is None
    assert clusters["legacy 1"].id not in {clusters["harbour 1"].id, clusters["river"].id}


async def test_tenant_event_never_joins_a_legacy_cluster(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    harbour = await organization(session_factory, "harbour")
    legacy_event = await report_event(
        session_factory, await add_source(session_factory, None), "Bridge closed", occurred_at=DAY
    )
    await EventLinkingService(session_factory).link_event(legacy_event)
    tenant_event = await report_event(
        session_factory,
        await add_source(session_factory, harbour),
        "Bridge closed",
        occurred_at=DAY,
    )

    link = await EventLinkingService(session_factory).link_event(tenant_event)

    assert link is not None and link.created_cluster
    tenant_cluster = await cluster_of(session_factory, tenant_event)
    legacy_cluster = await cluster_of(session_factory, legacy_event)
    assert tenant_cluster is not None and legacy_cluster is not None
    assert tenant_cluster.id != legacy_cluster.id
    assert tenant_cluster.organization_id == harbour


async def test_event_with_evidence_in_two_organizations_is_not_linked(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    harbour = await organization(session_factory, "harbour")
    river = await organization(session_factory, "river")
    _, [harbour_chunk] = await add_document(
        session_factory, await add_source(session_factory, harbour), "h", ["Flood h."]
    )
    _, [river_chunk] = await add_document(
        session_factory, await add_source(session_factory, river), "r", ["Flood r."]
    )
    async with session_factory() as session:
        event = Event(event_type="flood", title="Harbour flood", occurred_at=DAY)
        session.add(event)
        await session.flush()
        session.add_all(
            EventEvidence(event_id=event.id, chunk_id=chunk, provider="test", model="m")
            for chunk in (harbour_chunk, river_chunk)
        )
        await session.commit()

    with pytest.raises(EventOwnershipError):
        await EventLinkingService(session_factory).link_event(event.id)
    result = await EventLinkingService(session_factory).link_unclustered()

    assert (result.events_checked, result.events_linked) == (1, 0)
    assert await cluster_of(session_factory, event.id) is None


async def test_concurrent_links_in_one_organization_share_a_cluster(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    harbour = await organization(session_factory, "harbour")
    source = await add_source(session_factory, harbour)
    events = [
        await report_event(session_factory, source, "Port closed", occurred_at=DAY)
        for _ in range(4)
    ]
    linker = EventLinkingService(session_factory)

    links = await asyncio.gather(*(linker.link_event(event) for event in events))

    assert len({link.cluster_id for link in links if link is not None}) == 1
    assert sum(link.created_cluster for link in links if link is not None) == 1
