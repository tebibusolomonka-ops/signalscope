import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.ingestion.service import IngestionRunService

pytestmark = pytest.mark.anyio


async def create_source(client: httpx.AsyncClient, name: str) -> str:
    response = await client.post(
        "/sources", json={"type": "rss", "name": name, "url": "https://example.com/rss"}
    )
    assert response.status_code == 201
    source_id: str = response.json()["id"]
    return source_id


async def create_run(client: httpx.AsyncClient, source_id: str) -> dict[str, Any]:
    response = await client.post("/ingestion-runs", json={"source_id": source_id})
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


@pytest.fixture
async def source_id(client: httpx.AsyncClient) -> str:
    return await create_source(client, "Example feed")


async def test_create_ingestion_run(client: httpx.AsyncClient, source_id: str) -> None:
    run = await create_run(client, source_id)

    assert uuid.UUID(run["id"])
    assert run["source_id"] == source_id
    assert run["status"] == "pending"
    assert run["started_at"] is None
    assert run["finished_at"] is None
    assert run["error_message"] is None


async def test_create_ingestion_run_for_unknown_source(client: httpx.AsyncClient) -> None:
    response = await client.post("/ingestion-runs", json={"source_id": str(uuid.uuid4())})

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Source was not found."}}


async def test_get_ingestion_run(client: httpx.AsyncClient, source_id: str) -> None:
    run = await create_run(client, source_id)

    response = await client.get(f"/ingestion-runs/{run['id']}")

    assert response.status_code == 200
    assert response.json() == run


async def test_get_unknown_ingestion_run(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/ingestion-runs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Ingestion run was not found."},
    }


async def test_list_ingestion_runs_with_pagination(
    client: httpx.AsyncClient, source_id: str
) -> None:
    runs = [await create_run(client, source_id) for _ in range(3)]

    first_page = (await client.get("/ingestion-runs")).json()
    second_page = (await client.get("/ingestion-runs", params={"limit": 2, "offset": 2})).json()

    assert first_page == {"items": runs, "total": 3, "limit": 50, "offset": 0}
    assert second_page == {"items": runs[2:], "total": 3, "limit": 2, "offset": 2}


async def test_list_ingestion_runs_by_source(client: httpx.AsyncClient, source_id: str) -> None:
    other_source_id = await create_source(client, "Other feed")
    run = await create_run(client, source_id)
    await create_run(client, other_source_id)

    response = await client.get("/ingestion-runs", params={"source_id": source_id})

    assert response.json()["items"] == [run]
    assert response.json()["total"] == 1


async def test_list_ingestion_runs_by_status(
    client: httpx.AsyncClient,
    source_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    pending = await create_run(client, source_id)
    started = await create_run(client, source_id)
    async with session_factory() as session:
        await IngestionRunService(session).mark_running(uuid.UUID(started["id"]))

    running = (await client.get("/ingestion-runs", params={"status": "running"})).json()
    waiting = (await client.get("/ingestion-runs", params={"status": "pending"})).json()

    assert [run["id"] for run in running["items"]] == [started["id"]]
    assert running["items"][0]["started_at"] is not None
    assert waiting["items"] == [pending]
