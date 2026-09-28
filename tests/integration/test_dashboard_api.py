import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from signalscope.domain.events.linking import EventLinkingService

pytestmark = pytest.mark.anyio


async def test_overview(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await create_source(session_factory, "Wire")
    await report_event(session_factory, source, "Harbour flood")

    response = await client.get("/dashboard/overview")

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["sources"], body["documents"], body["chunks"], body["events"]) == (1, 1, 1, 1)
    assert body["pending_events"] == 0


async def test_source_series(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    await report_event(session_factory, wire, "Harbour flood")
    await report_event(session_factory, paper, "Bridge closed")

    everything = (await client.get("/dashboard/sources", params={"days": 7})).json()
    only_wire = (
        await client.get("/dashboard/sources", params={"days": 1, "source_id": str(wire)})
    ).json()

    assert (everything["days"], everything["source_id"], len(everything["items"])) == (7, None, 7)
    # The documents were stored today, the last day of the series.
    assert everything["items"][-1]["documents_created"] == 2
    assert sum(item["documents_created"] for item in everything["items"]) == 2
    assert only_wire["items"][0]["documents_created"] == 1


async def test_event_series(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    today = datetime.now(UTC).replace(hour=0, minute=30, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    await report_event(session_factory, wire, "Harbour flood", occurred_at=today)
    await report_event(session_factory, paper, "Harbour flood", occurred_at=today)
    await report_event(
        session_factory, paper, "Bridge closed", event_type="closure", occurred_at=yesterday
    )
    await EventLinkingService(session_factory).link_unclustered()

    body = (await client.get("/dashboard/events", params={"days": 2})).json()
    floods = (
        await client.get("/dashboard/events", params={"days": 2, "event_type": "flood"})
    ).json()

    assert [
        (item["events"], item["clusters"], item["cross_source_clusters"]) for item in body["items"]
    ] == [(1, 1, 0), (2, 1, 1)]
    assert [item["events"] for item in floods["items"]] == [0, 2]
    assert floods["event_type"] == "flood"


async def test_unknown_source(client: httpx.AsyncClient) -> None:
    missing = str(uuid.uuid4())

    sources = await client.get("/dashboard/sources", params={"source_id": missing})
    events = await client.get("/dashboard/events", params={"source_id": missing})

    assert (sources.status_code, events.status_code) == (404, 404)
