import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from signalscope.core.errors import NotFoundError
from signalscope.domain.events.cluster_detail import EventClusterDetail, EventClusterDetailService
from signalscope.domain.events.linking import EventLinkingService

pytestmark = pytest.mark.anyio

MARCH_4 = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)


async def detail(
    session_factory: async_sessionmaker[AsyncSession], event_id: uuid.UUID
) -> EventClusterDetail:
    link = await EventLinkingService(session_factory).link_event(event_id)
    assert link is not None
    async with session_factory() as session:
        return await EventClusterDetailService(session).get(link.cluster_id)


async def test_single_event(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory, "Wire")
    event = await report_event(session_factory, source, "Harbour flood", occurred_at=MARCH_4)

    found = await detail(session_factory, event)

    assert (found.event_type, found.title, found.occurred_at) == ("flood", "Harbour flood", MARCH_4)
    assert (found.event_count, found.source_count, found.evidence_count) == (1, 1, 1)
    [member] = found.members
    assert (member.event_id, member.title, member.summary) == (event, "Harbour flood", None)
    [evidence] = member.evidence
    assert (evidence.source_id, evidence.source_name) == (source, "Wire")
    assert (evidence.provider, evidence.model, evidence.confidence) == ("test", "m", None)
    assert evidence.chunk_metadata == {}


async def test_several_events_and_sources_in_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    undated = await report_event(session_factory, wire, "Harbour flood")
    later = await report_event(
        session_factory, paper, "Harbour flood", occurred_at=MARCH_4 + timedelta(hours=5)
    )
    earlier = await report_event(
        session_factory, paper, "Harbour flood", occurred_at=MARCH_4, evidence_count=2
    )
    await EventLinkingService(session_factory).link_unclustered()

    found = await detail(session_factory, undated)

    # Dated members first, oldest first; undated last.
    assert [member.event_id for member in found.members] == [earlier, later, undated]
    assert (found.event_count, found.source_count, found.evidence_count) == (3, 2, 4)
    assert [len(member.evidence) for member in found.members] == [2, 1, 1]
    assert {item.source_name for member in found.members for item in member.evidence} == {
        "Wire",
        "Paper",
    }
    assert found.occurred_at == MARCH_4


async def test_unknown_cluster(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError, match="Event cluster was not found"):
            await EventClusterDetailService(session).get(uuid.uuid4())
