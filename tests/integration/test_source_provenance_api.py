import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from signalscope.domain.documents.model import Document
from signalscope.domain.events.linking import EventLinkingService

pytestmark = pytest.mark.anyio

MARCH_4 = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)


async def provenance(client: httpx.AsyncClient, source_id: uuid.UUID) -> dict[str, Any]:
    response = await client.get(f"/sources/{source_id}/provenance")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_empty_source(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await create_source(session_factory, "Quiet")

    assert await provenance(client, source) == {
        "source_id": str(source),
        "document_count": 0,
        "first_document_at": None,
        "last_document_at": None,
        "first_published_at": None,
        "last_published_at": None,
        "entity_count": 0,
        "claim_count": 0,
        "event_count": 0,
        "event_cluster_count": 0,
        "cross_source_event_cluster_count": 0,
        "revision_count": 0,
    }


async def test_populated_source(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    async with session_factory() as session:
        session.add(Document(source_id=wire, published_at=MARCH_4))
        await session.commit()
    await report_event(session_factory, wire, "Harbour flood", occurred_at=MARCH_4)
    await report_event(session_factory, paper, "Harbour flood", occurred_at=MARCH_4)
    await report_event(session_factory, wire, "Bridge closed", event_type="closure")
    await EventLinkingService(session_factory).link_unclustered()

    body = await provenance(client, wire)

    assert body["document_count"] == 3
    assert datetime.fromisoformat(body["first_published_at"]) == MARCH_4
    assert body["first_document_at"] is not None
    assert (body["event_count"], body["event_cluster_count"]) == (2, 2)
    assert body["cross_source_event_cluster_count"] == 1


async def test_unknown_source(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/sources/{uuid.uuid4()}/provenance")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Source was not found."
