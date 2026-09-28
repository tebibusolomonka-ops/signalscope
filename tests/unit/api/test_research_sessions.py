import uuid
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

    assert set(paths["/research/sessions"]) == {"post"}
    assert set(paths["/research/sessions/{session_id}"]) == {"get"}
    assert set(paths["/research/sessions/{session_id}/turns"]) == {"get", "post"}
    assert set(schemas["ResearchTurnRead"]["properties"]) == {
        "id",
        "sequence",
        "question",
        "answer",
        "citation_ids",
        "citations",
        "evidence",
        "created_at",
    }
    # No prompts or model internals are shown.
    assert "text" not in schemas["TurnEvidenceRead"]["properties"]
    assert set(schemas["ResearchTurnResponse"]["properties"]) == {"session", "turn"}


def post(path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.post(path, json=body)
    result: dict[str, Any] = response.json()
    return response.status_code, result


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"retrieval_mode": "fuzzy"}, "retrieval_mode"),
        ({"source_id": "not-a-uuid"}, "source_id"),
        ({"title": " "}, "title"),
        ({"owner": "me"}, "owner"),
    ],
    ids=["bad mode", "bad source", "blank title", "unknown field"],
)
def test_bad_session_request(body: dict[str, Any], field: str) -> None:
    status_code, result = post("/research/sessions", body)

    assert status_code == 422
    assert result["error"]["details"][0]["loc"][-1] == field


@pytest.mark.parametrize(
    "body",
    [{}, {"question": " "}, {"question": "floods", "limit": 0}],
    ids=["no question", "blank question", "bad limit"],
)
def test_bad_turn_request(body: dict[str, Any]) -> None:
    status_code, _ = post(f"/research/sessions/{uuid.uuid4()}/turns", body)

    assert status_code == 422


def test_needs_a_database(client: TestClient) -> None:
    assert client.post("/research/sessions", json={}).status_code == 503


def test_export_route_is_in_openapi(app: FastAPI) -> None:
    get = app.openapi()["paths"]["/research/sessions/{session_id}/export"]["get"]

    assert [parameter["name"] for parameter in get["parameters"]] == ["session_id", "format"]
    assert set(get["responses"]["200"]["content"]) == {"application/json", "text/markdown"}
    schema = app.openapi()["components"]["schemas"]["ResearchSessionExport"]
    assert set(schema["properties"]) == {"session", "turns"}


def test_export_bad_format() -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.get(f"/research/sessions/{uuid.uuid4()}/export", params={"format": "pdf"})

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["query", "format"]
