import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, so any connection attempt would fail.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_ingestion_runs_need_a_database(client: TestClient) -> None:
    create = client.post("/ingestion-runs", json={"source_id": str(uuid.uuid4())})
    listing = client.get("/ingestion-runs")

    for response in [create, listing]:
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "service_unavailable"


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, "source_id"),
        ({"source_id": "not-a-uuid"}, "source_id"),
        ({"source_id": str(uuid.uuid4()), "status": "completed"}, "status"),
        ({"source_id": str(uuid.uuid4()), "error_message": "x"}, "error_message"),
    ],
)
def test_invalid_create_body_is_rejected(body: dict[str, Any], field: str) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app) as client:
        response = client.post("/ingestion-runs", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["body", field]


@pytest.mark.parametrize(
    ("path", "params", "location"),
    [
        ("/ingestion-runs/not-a-uuid", {}, ["path", "run_id"]),
        ("/ingestion-runs", {"status": "cancelled"}, ["query", "status"]),
        ("/ingestion-runs", {"source_id": "nope"}, ["query", "source_id"]),
        ("/ingestion-runs", {"limit": 0}, ["query", "limit"]),
    ],
)
def test_invalid_request_values_are_rejected(
    path: str, params: dict[str, Any], location: list[str]
) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app) as client:
        response = client.get(path, params=params)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == location


def test_ingestion_run_routes_are_in_openapi(app: FastAPI) -> None:
    paths = {path: set(methods) for path, methods in app.openapi()["paths"].items()}

    assert paths["/ingestion-runs"] == {"get", "post"}
    assert paths["/ingestion-runs/{run_id}"] == {"get"}
    assert [path for path in paths if path.startswith("/ingestion-runs")] == [
        "/ingestion-runs",
        "/ingestion-runs/{run_id}",
    ]
