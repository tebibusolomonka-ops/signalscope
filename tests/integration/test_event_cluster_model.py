import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.events.cluster import EventCluster, EventClusterMember
from signalscope.domain.events.model import Event

pytestmark = pytest.mark.anyio


async def create_event(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        event = Event(event_type="flood", title="River flood")
        session.add(event)
        await session.commit()
        return event.id


async def create_cluster(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        cluster = EventCluster(
            event_type="flood", canonical_title="River Flood", normalized_title="river flood"
        )
        session.add(cluster)
        await session.commit()
        return cluster.id


async def add_member(
    session_factory: async_sessionmaker[AsyncSession], cluster_id: uuid.UUID, event_id: uuid.UUID
) -> None:
    async with session_factory() as session:
        session.add(EventClusterMember(cluster_id=cluster_id, event_id=event_id))
        await session.commit()


async def members(session_factory: async_sessionmaker[AsyncSession]) -> list[EventClusterMember]:
    async with session_factory() as session:
        return list(await session.scalars(select(EventClusterMember)))


async def test_cluster_with_members(session_factory: async_sessionmaker[AsyncSession]) -> None:
    cluster = await create_cluster(session_factory)
    first, second = await create_event(session_factory), await create_event(session_factory)

    await add_member(session_factory, cluster, first)
    await add_member(session_factory, cluster, second)

    saved = await members(session_factory)
    assert {member.event_id for member in saved} == {first, second}
    assert {member.cluster_id for member in saved} == {cluster}
    assert all(member.created_at is not None for member in saved)
    async with session_factory() as session:
        stored = await session.get(EventCluster, cluster)
    assert stored is not None
    assert (stored.occurred_at, stored.created_at is not None) == (None, True)


async def test_an_event_is_in_one_cluster_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first, second = await create_cluster(session_factory), await create_cluster(session_factory)
    event = await create_event(session_factory)
    await add_member(session_factory, first, event)

    with pytest.raises(IntegrityError):
        await add_member(session_factory, second, event)


async def test_deleting_an_event_deletes_its_membership(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cluster = await create_cluster(session_factory)
    event = await create_event(session_factory)
    await add_member(session_factory, cluster, event)

    async with session_factory() as session:
        await session.execute(delete(Event).where(Event.id == event))
        await session.commit()

    assert await members(session_factory) == []
    async with session_factory() as session:
        assert await session.get(EventCluster, cluster) is not None


async def test_deleting_a_cluster_keeps_its_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cluster = await create_cluster(session_factory)
    event = await create_event(session_factory)
    await add_member(session_factory, cluster, event)

    async with session_factory() as session:
        await session.execute(delete(EventCluster).where(EventCluster.id == cluster))
        await session.commit()

    assert await members(session_factory) == []
    async with session_factory() as session:
        assert await session.get(Event, event) is not None


@pytest.mark.parametrize(
    "values",
    [
        {"event_type": " "},
        {"canonical_title": ""},
        {"normalized_title": " "},
    ],
    ids=["blank type", "blank title", "blank normalized title"],
)
async def test_blank_values_are_rejected(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, str]
) -> None:
    fields = {"event_type": "flood", "canonical_title": "Flood", "normalized_title": "flood"}
    async with session_factory() as session:
        session.add(EventCluster(**(fields | values)))
        with pytest.raises(IntegrityError):
            await session.commit()
