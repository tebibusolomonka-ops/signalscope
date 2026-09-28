import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from signalscope.domain.events.linking import EventLinkingService

pytestmark = pytest.mark.anyio


async def compare(client: httpx.AsyncClient, *source_ids: uuid.UUID) -> httpx.Response:
    return await client.post(
        "/sources/compare", json={"source_ids": [str(source_id) for source_id in source_ids]}
    )


async def test_two_sources(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    await report_event(session_factory, wire, "Harbour flood")
    await report_event(session_factory, wire, "Bridge closed", event_type="closure")

    response = await compare(client, paper, wire)

    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert [item["source"]["name"] for item in body["sources"]] == ["Paper", "Wire"]
    assert [item["provenance"]["event_count"] for item in body["sources"]] == [0, 2]
    assert [item["provenance"]["source_id"] for item in body["sources"]] == [str(paper), str(wire)]
    assert (
        body["shared_event_cluster_count"],
        body["shared_entity_count"],
        body["shared_claim_count"],
    ) == (0, 0, 0)


async def test_shared_event_cluster(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    radio = await create_source(session_factory, "Radio")
    await report_event(session_factory, wire, "Harbour flood")
    await report_event(session_factory, paper, "Harbour flood")
    await report_event(session_factory, radio, "Market fire", event_type="fire")
    await EventLinkingService(session_factory).link_unclustered()

    body = (await compare(client, wire, paper, radio)).json()

    assert body["shared_event_cluster_count"] == 1
    assert [item["provenance"]["cross_source_event_cluster_count"] for item in body["sources"]] == [
        1,
        1,
        0,
    ]


async def test_unknown_source(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    wire = await create_source(session_factory, "Wire")
    missing = uuid.uuid4()

    response = await compare(client, wire, missing)

    assert response.status_code == 404
    assert response.json()["error"]["message"] == f"Source was not found: {missing}."
