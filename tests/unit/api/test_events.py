from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_routes_are_in_openapi(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    schemas = app.openapi()["components"]["schemas"]

    assert {parameter["name"] for parameter in paths["/events"]["get"]["parameters"]} == {
        "event_type",
        "occurred_from",
        "occurred_to",
        "limit",
        "offset",
    }
    # Events come from extraction, so there is no way to write them.
    assert set(paths["/events"]) == {"get"}
    assert set(paths["/events/{event_id}"]) == {"get"}
    assert set(schemas["EventEvidenceRead"]["properties"]) == {
        "document_id",
        "chunk_id",
        "confidence",
        "provider",
        "model",
        "chunk_metadata",
    }


def get(path: str, params: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.get(path, params=params)
    body: dict[str, Any] = response.json()
    return response.status_code, body


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"event_type": " "}, "event_type"),
        ({"occurred_from": "yesterday"}, "occurred_from"),
        ({"occurred_to": "2026-09-01T00:00:00"}, "occurred_to"),
        ({"limit": "101"}, "limit"),
    ],
    ids=["blank type", "not a time", "time without zone", "limit too large"],
)
def test_bad_request(params: dict[str, str], field: str) -> None:
    status_code, body = get("/events", params)

    assert status_code == 422
    assert body["error"]["details"][0]["loc"] == ["query", field]


def test_needs_a_database(client: TestClient) -> None:
    assert client.get("/events").status_code == 503
