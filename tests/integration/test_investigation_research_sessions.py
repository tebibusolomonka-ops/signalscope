import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event

pytestmark = pytest.mark.anyio


async def create_investigation(client: httpx.AsyncClient) -> str:
    response = await client.post("/investigations", json={"title": "Harbour floods"})
    assert response.status_code == 201, response.text
    investigation_id: str = response.json()["id"]
    return investigation_id


async def research_session_with_turns(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> dict[str, Any]:
    source = await create_source(session_factory, "Wire")
    await report_event(session_factory, source, "Harbour flood")
    response = await client.post(
        "/research/sessions",
        json={"title": "Floods", "retrieval_mode": "lexical", "source_id": str(source)},
    )
    research: dict[str, Any] = response.json()
    for question in ("harbour flood", "harbour"):
        turn = await client.post(
            f"/research/sessions/{research['id']}/turns", json={"question": question}
        )
        assert turn.status_code == 201, turn.text
    return research


async def test_save_session_once(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    investigation_id = await create_investigation(client)
    research = await research_session_with_turns(client, session_factory)
    path = f"/investigations/{investigation_id}/research-sessions/{research['id']}"

    first = await client.post(path)
    again = await client.post(path)

    assert first.status_code == 201, first.text
    item = first.json()
    assert (item["item_type"], item["reference_id"]) == ("research_session", research["id"])
    snapshot = item["snapshot"]
    assert (snapshot["title"], snapshot["retrieval_mode"], snapshot["source_id"]) == (
        "Floods",
        "lexical",
        research["source_id"],
    )
    assert snapshot["turn_count"] == 2
    assert snapshot["latest_turn_at"] is not None
    # Saving again returns the same item and does not add another.
    assert again.status_code == 200
    assert again.json()["id"] == item["id"]
    items = (await client.get(f"/investigations/{investigation_id}/items")).json()
    assert [row["id"] for row in items] == [item["id"]]


async def test_unknown_investigation_or_session(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    investigation_id = await create_investigation(client)
    research = await research_session_with_turns(client, session_factory)

    unknown_investigation = await client.post(
        f"/investigations/{uuid.uuid4()}/research-sessions/{research['id']}"
    )
    unknown_session = await client.post(
        f"/investigations/{investigation_id}/research-sessions/{uuid.uuid4()}"
    )

    assert unknown_investigation.status_code == 404
    assert unknown_session.status_code == 404
    assert unknown_session.json()["error"]["message"] == (
        "The research session to save was not found."
    )


async def test_closed_investigation_rejects_the_save(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    investigation_id = await create_investigation(client)
    research = await research_session_with_turns(client, session_factory)
    await client.patch(f"/investigations/{investigation_id}", json={"status": "closed"})

    response = await client.post(
        f"/investigations/{investigation_id}/research-sessions/{research['id']}"
    )

    assert response.status_code == 409
