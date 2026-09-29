import io
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from event_reports import report_event
from signalscope.cli import assign_source_organization
from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.core.settings import Settings
from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.linking import EventLinkingService
from signalscope.domain.research.session import ResearchSession
from signalscope.domain.sources.model import Source
from signalscope.domain.tenancy.assignment import LegacySourceAssignmentService
from tenancy_helpers import Tenants, add_document, add_source, make_tenants

pytestmark = pytest.mark.anyio

DAY = datetime(2026, 9, 1, 12, tzinfo=UTC)


class World:
    tenants: Tenants
    moving: uuid.UUID
    staying: uuid.UUID
    moving_event: uuid.UUID
    staying_event: uuid.UUID
    scoped_session: uuid.UUID
    open_session: uuid.UUID


@pytest.fixture
async def world(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> World:
    """Two legacy sources that report the same event, so it is one legacy cluster."""
    found = World()
    found.tenants = await make_tenants(auth_client, session_factory)
    found.moving = await add_source(session_factory, None, "moving feed")
    found.staying = await add_source(session_factory, None, "staying feed")
    await add_document(session_factory, found.moving, "moving-doc", ["Harbour flood notes."])
    found.moving_event = await report_event(
        session_factory, found.moving, "Harbour flood", occurred_at=DAY
    )
    found.staying_event = await report_event(
        session_factory, found.staying, "Harbour flood", occurred_at=DAY
    )
    await EventLinkingService(session_factory).link_unclustered()
    async with session_factory() as session:
        scoped = ResearchSession(title="Scoped", source_id=found.moving)
        unscoped = ResearchSession(title="Open")
        session.add_all([scoped, unscoped])
        await session.commit()
        found.scoped_session, found.open_session = scoped.id, unscoped.id
    return found


async def cluster_of(
    session_factory: async_sessionmaker[AsyncSession], event_id: uuid.UUID
) -> EventCluster | None:
    async with session_factory() as session:
        return await session.scalar(
            select(EventCluster)
            .join(EventClusterMember, EventClusterMember.cluster_id == EventCluster.id)
            .where(EventClusterMember.event_id == event_id)
        )


async def test_assign_moves_content_and_relinks_events(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    world: World,
) -> None:
    a = world.tenants.a
    old_cluster = await cluster_of(session_factory, world.staying_event)
    assert old_cluster is not None

    result = await LegacySourceAssignmentService(session_factory).assign(world.moving, a.id)

    assert (result.documents, result.events_relinked, result.research_sessions) == (2, 1, 1)
    new_cluster = await cluster_of(session_factory, world.moving_event)
    kept_cluster = await cluster_of(session_factory, world.staying_event)
    assert new_cluster is not None and kept_cluster is not None
    assert new_cluster.organization_id == a.id
    # The other legacy event stays in its legacy cluster, now alone.
    assert kept_cluster.id == old_cluster.id and kept_cluster.organization_id is None
    async with session_factory() as session:
        members = list(
            await session.scalars(
                select(EventClusterMember.event_id).where(
                    EventClusterMember.cluster_id == old_cluster.id
                )
            )
        )
        scoped = await session.get_one(ResearchSession, world.scoped_session)
        unscoped = await session.get_one(ResearchSession, world.open_session)
    assert members == [world.staying_event]
    assert (scoped.organization_id, unscoped.organization_id) == (a.id, None)

    listed = await auth_client.get(f"/documents?{a.query}", headers=a.headers["viewer"])
    assert {item["title"] for item in listed.json()["items"]} == {"moving-doc", "Harbour flood"}
    timeline = await auth_client.get(f"/timeline?{a.query}", headers=a.headers["viewer"])
    [item] = timeline.json()["items"]
    assert [source["name"] for source in item["sources"]] == ["moving feed"]


async def test_rules(session_factory: async_sessionmaker[AsyncSession], world: World) -> None:
    service = LegacySourceAssignmentService(session_factory)
    a, b = world.tenants.a, world.tenants.b

    with pytest.raises(NotFoundError, match="Source"):
        await service.assign(uuid.uuid4(), a.id)
    with pytest.raises(NotFoundError, match="Organization"):
        await service.assign(world.moving, uuid.uuid4())
    await service.assign(world.moving, a.id)
    with pytest.raises(ConflictError):
        await service.assign(world.moving, b.id)
    with pytest.raises(ConflictError):
        await service.assign(world.moving, a.id)


async def test_failed_assignment_changes_nothing(
    session_factory: async_sessionmaker[AsyncSession], world: World
) -> None:
    cluster_before = await cluster_of(session_factory, world.moving_event)

    with pytest.raises(NotFoundError):
        await LegacySourceAssignmentService(session_factory).assign(world.moving, uuid.uuid4())

    async with session_factory() as session:
        source = await session.get_one(Source, world.moving)
        scoped = await session.get_one(ResearchSession, world.scoped_session)
    assert (source.organization_id, scoped.organization_id) == (None, None)
    cluster_after = await cluster_of(session_factory, world.moving_event)
    assert cluster_before is not None and cluster_after is not None
    assert cluster_after.id == cluster_before.id


async def test_command_output(
    database_engine: AsyncEngine,
    migrated_database: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    world: World,
) -> None:
    settings = Settings(database_url=migrated_database.database_url)
    out, err = io.StringIO(), io.StringIO()

    code = await assign_source_organization(world.moving, world.tenants.b.id, settings, out, err)
    again = await assign_source_organization(
        world.moving, world.tenants.b.id, settings, io.StringIO(), err
    )

    assert code == 0
    assert out.getvalue() == (
        f"Source: {world.moving}\n"
        f"Organization: {world.tenants.b.id}\n"
        "Documents affected: 2\n"
        "Events relinked: 1\n"
        "Research sessions assigned: 1\n"
    )
    assert again == 1
    assert err.getvalue() == "Error: The source already belongs to an organization.\n"
