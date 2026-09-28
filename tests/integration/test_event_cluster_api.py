import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.events.linking import EventLinkingService

pytestmark = pytest.mark.anyio

MARCH_4 = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)


async def test_timeline_item_leads_to_its_cluster(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    first = await report_event(session_factory, wire, "Harbour flood", occurred_at=MARCH_4)
    second = await report_event(session_factory, paper, "Harbour flood")
    async with session_factory() as session:
        chunk = await session.scalar(select(DocumentChunk).limit(1))
        assert chunk is not None
        chunk.chunk_metadata = {"page_number": 2}
        await session.commit()
    await EventLinkingService(session_factory).link_unclustered()
    [item] = (await client.get("/timeline")).json()["items"]

    response = await client.get(f"/event-clusters/{item['cluster_id']}")

    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert (body["cluster_id"], body["title"], body["event_type"]) == (
        item["cluster_id"],
        "Harbour flood",
        "flood",
    )
    assert (body["event_count"], body["source_count"], body["evidence_count"]) == (2, 2, 2)
    assert [member["event_id"] for member in body["members"]] == [str(first), str(second)]
    evidence = [row for member in body["members"] for row in member["evidence"]]
    assert {row["source_name"] for row in evidence} == {"Wire", "Paper"}
    assert {"page_number": 2} in [row["chunk_metadata"] for row in evidence]


async def test_unknown_cluster(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/event-clusters/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Event cluster was not found."
