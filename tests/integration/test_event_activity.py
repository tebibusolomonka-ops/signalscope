import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from signalscope.core.errors import InvalidInputError, NotFoundError
from signalscope.dashboard.events import EventActivityDay, EventActivityService
from signalscope.domain.events.linking import EventLinkingService

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def on(day: int) -> datetime:
    return datetime(2026, 3, day, 9, 0, tzinfo=UTC)


async def daily(
    session_factory: async_sessionmaker[AsyncSession],
    days: int = 3,
    event_type: str | None = None,
    source_id: uuid.UUID | None = None,
) -> list[EventActivityDay]:
    await EventLinkingService(session_factory).link_unclustered()
    async with session_factory() as session:
        return await EventActivityService(session, clock=lambda: NOW).daily(
            days, event_type, source_id
        )


def rows(found: list[EventActivityDay]) -> list[tuple[int, int, int, int]]:
    return [(day.date.day, day.events, day.clusters, day.cross_source_clusters) for day in found]


async def test_empty(session_factory: async_sessionmaker[AsyncSession]) -> None:
    found = await daily(session_factory, 7)

    assert [day.date for day in found] == [date(2026, 3, day) for day in range(4, 11)]
    assert all((day.events, day.clusters, day.cross_source_clusters) == (0, 0, 0) for day in found)


@pytest.fixture
async def sources(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, uuid.UUID]:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    # One flood reported by both sources on the 8th.
    await report_event(session_factory, wire, "Harbour flood", occurred_at=on(8))
    await report_event(session_factory, paper, "Harbour flood", occurred_at=on(8))
    # A closure only the wire reports on the 10th, and one with no date.
    await report_event(
        session_factory, wire, "Bridge closed", event_type="closure", occurred_at=on(10)
    )
    await report_event(session_factory, wire, "Market fire", event_type="fire")
    # Outside the three days.
    await report_event(session_factory, paper, "Old flood", occurred_at=on(1))
    return {"wire": wire, "paper": paper}


async def test_events_clusters_and_cross_source(
    session_factory: async_sessionmaker[AsyncSession], sources: dict[str, uuid.UUID]
) -> None:
    found = await daily(session_factory)

    assert rows(found) == [(8, 2, 1, 1), (9, 0, 0, 0), (10, 1, 1, 0)]


async def test_type_filter(
    session_factory: async_sessionmaker[AsyncSession], sources: dict[str, uuid.UUID]
) -> None:
    found = await daily(session_factory, event_type=" FLOOD ")

    assert rows(found) == [(8, 2, 1, 1), (9, 0, 0, 0), (10, 0, 0, 0)]


async def test_source_filter(
    session_factory: async_sessionmaker[AsyncSession], sources: dict[str, uuid.UUID]
) -> None:
    only_paper = await daily(session_factory, source_id=sources["paper"])

    # The shared cluster still counts as cross source; only the paper's own event counts.
    assert rows(only_paper) == [(8, 1, 1, 1), (9, 0, 0, 0), (10, 0, 0, 0)]


async def test_bounds_and_unknown_source(session_factory: async_sessionmaker[AsyncSession]) -> None:
    with pytest.raises(InvalidInputError):
        await daily(session_factory, 0)
    with pytest.raises(NotFoundError):
        await daily(session_factory, 3, source_id=uuid.uuid4())
