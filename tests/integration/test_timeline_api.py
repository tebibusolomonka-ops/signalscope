from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from signalscope.domain.events.linking import EventLinkingService

pytestmark = pytest.mark.anyio

MARCH_4 = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)


def day(number: int) -> datetime:
    return MARCH_4 + timedelta(days=number)


async def timeline(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession], **params: Any
) -> dict[str, Any]:
    await EventLinkingService(session_factory).link_unclustered()
    response = await client.get("/timeline", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def titles(body: dict[str, Any]) -> list[str]:
    return [item["title"] for item in body["items"]]


async def test_empty(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    assert await timeline(client, session_factory) == {
        "items": [],
        "total": 0,
        "limit": 50,
        "offset": 0,
    }


async def test_order(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await create_source(session_factory, "Wire")
    await report_event(session_factory, source, "Undated flood")
    await report_event(session_factory, source, "Flood 1", occurred_at=day(1))
    await report_event(session_factory, source, "Flood 5", occurred_at=day(5))

    newest = await timeline(client, session_factory)
    oldest = await timeline(client, session_factory, order="oldest_first")

    assert titles(newest) == ["Flood 5", "Flood 1", "Undated flood"]
    assert titles(oldest) == ["Flood 1", "Flood 5", "Undated flood"]


async def test_date_type_and_source_filters(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    await report_event(session_factory, wire, "Flood 1", occurred_at=day(1))
    await report_event(session_factory, paper, "Flood 5", occurred_at=day(5))
    await report_event(session_factory, wire, "Vote", event_type="election", occurred_at=day(5))

    dated = await timeline(
        client,
        session_factory,
        occurred_from=day(4).isoformat(),
        occurred_to=day(6).isoformat(),
    )
    floods = await timeline(client, session_factory, event_type="Flood")
    from_paper = await timeline(client, session_factory, source_id=str(paper))

    assert (sorted(titles(dated)), dated["total"]) == (["Flood 5", "Vote"], 2)
    assert titles(floods) == ["Flood 5", "Flood 1"]
    assert titles(from_paper) == ["Flood 5"]


async def test_pagination(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await create_source(session_factory, "Wire")
    for number in range(4):
        await report_event(session_factory, source, f"Flood {number}", occurred_at=day(number))

    body = await timeline(client, session_factory, limit=2, offset=2)

    assert (titles(body), body["total"], body["limit"], body["offset"]) == (
        ["Flood 1", "Flood 0"],
        4,
        2,
        2,
    )


async def test_multi_source_event(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    await report_event(session_factory, wire, "Harbour flood", occurred_at=MARCH_4)
    await report_event(session_factory, paper, "Harbour Flood", occurred_at=MARCH_4)

    [item] = (await timeline(client, session_factory))["items"]

    assert (item["title"], item["event_type"]) == ("Harbour flood", "flood")
    assert datetime.fromisoformat(item["occurred_at"]) == MARCH_4
    assert (item["event_count"], item["source_count"], item["evidence_count"]) == (2, 2, 2)
    assert [source["name"] for source in item["sources"]] == ["Paper", "Wire"]
    assert {source["source_id"] for source in item["sources"]} == {str(wire), str(paper)}


async def test_invalid_date_range(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/timeline", params={"occurred_from": day(5).isoformat(), "occurred_to": day(1).isoformat()}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"
