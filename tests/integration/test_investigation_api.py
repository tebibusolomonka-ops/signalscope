import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source, report_event

pytestmark = pytest.mark.anyio


async def create(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    response = await client.post("/investigations", json={"title": "Floods"} | body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


async def test_create_list_get_and_update(client: httpx.AsyncClient) -> None:
    first = await create(client, title="  Floods  ", description="Harbour notes")
    second = await create(client, title="Prices")

    assert (first["title"], first["description"], first["status"]) == (
        "Floods",
        "Harbour notes",
        "open",
    )
    listed = (await client.get("/investigations")).json()
    assert [item["id"] for item in listed["items"]] == [second["id"], first["id"]]
    assert listed["total"] == 2

    response = await client.patch(
        f"/investigations/{first['id']}", json={"title": "Harbour floods", "description": None}
    )
    assert response.status_code == 200, response.text
    assert (response.json()["title"], response.json()["description"]) == ("Harbour floods", None)
    fetched = (await client.get(f"/investigations/{first['id']}")).json()
    assert fetched["title"] == "Harbour floods"


async def test_close_filter_and_reopen(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    investigation = await create(client)
    await create(client, title="Still open")
    source = await create_source(session_factory, "Wire")
    path = f"/investigations/{investigation['id']}"

    closed = await client.patch(path, json={"status": "closed"})
    blocked = [
        await client.patch(path, json={"title": "New"}),
        await client.post(
            f"{path}/items", json={"item_type": "source", "reference_id": str(source)}
        ),
        await client.delete(path),
    ]
    only_closed = (await client.get("/investigations", params={"status": "closed"})).json()
    reopened = await client.patch(path, json={"status": "open"})

    assert closed.json()["status"] == "closed"
    assert [response.status_code for response in blocked] == [409, 409, 409]
    assert blocked[0].json()["error"]["message"] == (
        "Investigation is closed. Reopen it to change it."
    )
    assert [item["id"] for item in only_closed["items"]] == [investigation["id"]]
    assert reopened.json()["status"] == "open"


async def test_items(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await create_source(session_factory, "Wire")
    event = await report_event(session_factory, source, "Harbour flood")
    investigation = await create(client)
    items_path = f"/investigations/{investigation['id']}/items"

    added = await client.post(
        items_path, json={"item_type": "event", "reference_id": str(event), "label": "Key event"}
    )
    duplicate = await client.post(
        items_path, json={"item_type": "event", "reference_id": str(event)}
    )
    unknown = await client.post(
        items_path, json={"item_type": "claim", "reference_id": str(uuid.uuid4())}
    )
    await client.post(items_path, json={"item_type": "source", "reference_id": str(source)})

    assert added.status_code == 201, added.text
    item = added.json()
    assert (item["item_type"], item["label"], item["snapshot"]["title"]) == (
        "event",
        "Key event",
        "Harbour flood",
    )
    assert (duplicate.status_code, unknown.status_code) == (409, 404)
    listed = (await client.get(items_path)).json()
    assert [row["item_type"] for row in listed] == ["event", "source"]

    removed = await client.delete(f"{items_path}/{item['id']}")
    assert removed.status_code == 204
    assert [row["item_type"] for row in (await client.get(items_path)).json()] == ["source"]
    assert (await client.delete(f"{items_path}/{item['id']}")).status_code == 404


async def test_delete(client: httpx.AsyncClient) -> None:
    investigation = await create(client)

    response = await client.delete(f"/investigations/{investigation['id']}")

    assert response.status_code == 204
    assert (await client.get(f"/investigations/{investigation['id']}")).status_code == 404


async def test_unknown_investigation(client: httpx.AsyncClient) -> None:
    missing = f"/investigations/{uuid.uuid4()}"

    responses = [
        await client.get(missing),
        await client.patch(missing, json={"title": "New"}),
        await client.delete(missing),
        await client.get(f"{missing}/items"),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404]
