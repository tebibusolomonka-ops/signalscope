from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_route_is_in_openapi(app: FastAPI) -> None:
    openapi = app.openapi()
    post = openapi["paths"]["/research/context"]["post"]
    schemas = openapi["components"]["schemas"]

    assert post["tags"] == ["Research"]
    assert set(schemas["ResearchContextRequest"]["properties"]) == {
        "query",
        "mode",
        "limit",
        "source_id",
    }
    assert set(schemas["ResearchContextResponse"]["properties"]) == {
        "query",
        "mode",
        "evidence",
        "context_text",
    }
    # The full chunk text is only in context_text.
    assert "text" not in schemas["ResearchEvidenceRead"]["properties"]


def post(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.post("/research/context", json=body)
    result: dict[str, Any] = response.json()
    return response.status_code, result


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"query": "  "}, "query"),
        ({}, "query"),
        ({"query": "wind", "mode": "fuzzy"}, "mode"),
        ({"query": "wind", "limit": 0}, "limit"),
        ({"query": "wind", "limit": 21}, "limit"),
        ({"query": "wind", "source_id": "nope"}, "source_id"),
    ],
    ids=["blank query", "no query", "unknown mode", "limit zero", "limit too large", "bad source"],
)
def test_bad_request(body: dict[str, Any], field: str) -> None:
    status_code, result = post(body)

    assert status_code == 422
    assert result["error"]["details"][0]["loc"] == ["body", field]


def test_reranked_mode_without_a_reranker() -> None:
    status_code, result = post({"query": "wind", "mode": "reranked"})

    assert status_code == 503
    assert "Reranker" in result["error"]["message"]


def test_needs_a_database(client: TestClient) -> None:
    response = client.post("/research/context", json={"query": "wind"})

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Database is not configured."
