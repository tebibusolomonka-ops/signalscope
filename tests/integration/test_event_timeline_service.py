from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from signalscope.domain.events.linking import EventLinkingService
from signalscope.domain.events.timeline import (
    EventTimelineService,
    TimelineEntry,
    TimelineFilters,
    TimelineOrder,
)

pytestmark = pytest.mark.anyio

MARCH_4 = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)


async def timeline(
    session_factory: async_sessionmaker[AsyncSession],
    filters: TimelineFilters | None = None,
    limit: int = 50,
    offset: int = 0,
    order: TimelineOrder = TimelineOrder.NEWEST_FIRST,
) -> tuple[list[TimelineEntry], int]:
    await EventLinkingService(session_factory).link_unclustered()
    async with session_factory() as session:
        return await EventTimelineService(session).page(
            filters or TimelineFilters(), limit, offset, order
        )


def titles(entries: list[TimelineEntry]) -> list[str]:
    return [entry.title for entry in entries]


async def test_empty(session_factory: async_sessionmaker[AsyncSession]) -> None:
    assert await timeline(session_factory) == ([], 0)


async def test_newest_first_then_unknown_times(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory, "Wire")
    await report_event(session_factory, source, "Undated flood")
    await report_event(session_factory, source, "Old flood", occurred_at=MARCH_4)
    await report_event(
        session_factory, source, "New flood", occurred_at=MARCH_4 + timedelta(days=9)
    )

    newest, total = await timeline(session_factory)
    oldest, _ = await timeline(session_factory, order=TimelineOrder.OLDEST_FIRST)

    assert total == 3
    assert titles(newest) == ["New flood", "Old flood", "Undated flood"]
    assert titles(oldest) == ["Old flood", "New flood", "Undated flood"]


async def test_date_range_and_type(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory, "Wire")
    await report_event(session_factory, source, "Undated flood")
    await report_event(session_factory, source, "Early flood", occurred_at=MARCH_4)
    await report_event(
        session_factory, source, "Late flood", occurred_at=MARCH_4 + timedelta(days=9)
    )
    await report_event(session_factory, source, "Vote", event_type="election", occurred_at=MARCH_4)

    in_range, total = await timeline(
        session_factory,
        TimelineFilters(
            occurred_from=MARCH_4 - timedelta(days=1), occurred_to=MARCH_4 + timedelta(days=1)
        ),
    )
    floods, _ = await timeline(session_factory, TimelineFilters(event_type=" FLOOD "))

    assert (sorted(titles(in_range)), total) == (["Early flood", "Vote"], 2)
    assert titles(floods) == ["Late flood", "Early flood", "Undated flood"]


async def test_multi_source_cluster(session_factory: async_sessionmaker[AsyncSession]) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    await report_event(session_factory, wire, "Harbour flood", occurred_at=MARCH_4)
    await report_event(session_factory, paper, "harbour  FLOOD", occurred_at=MARCH_4)
    await report_event(session_factory, wire, "Harbour flood", evidence_count=2)

    [entry], total = await timeline(session_factory)

    assert total == 1
    assert (entry.title, entry.event_type, entry.occurred_at) == ("Harbour flood", "flood", MARCH_4)
    assert (entry.event_count, entry.source_count, entry.evidence_count) == (3, 2, 4)
    assert [source.name for source in entry.sources] == ["Paper", "Wire"]


async def test_source_filter_keeps_the_whole_cluster(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    await report_event(session_factory, wire, "Harbour flood")
    await report_event(session_factory, paper, "Harbour flood")
    await report_event(session_factory, paper, "Bridge closed", event_type="closure")

    [entry], total = await timeline(session_factory, TimelineFilters(source_id=wire))

    assert (entry.title, total) == ("Harbour flood", 1)
    # The counts still cover every source that reports the cluster.
    assert entry.source_count == 2


async def test_pagination(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory, "Wire")
    for day in range(5):
        await report_event(
            session_factory, source, f"Flood {day}", occurred_at=MARCH_4 + timedelta(days=day)
        )

    page, total = await timeline(session_factory, limit=2, offset=1)

    assert (titles(page), total) == (["Flood 3", "Flood 2"], 5)
