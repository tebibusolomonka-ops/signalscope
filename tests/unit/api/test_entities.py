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
    parameters = {parameter["name"] for parameter in paths["/entities"]["get"]["parameters"]}

    assert parameters == {"query", "entity_type", "limit", "offset"}
    assert paths["/entities"]["get"]["tags"] == ["Entities"]
    assert set(paths["/entities/{entity_id}"]) == {"get"}
    # Entities come from extraction, so there is no way to write them.
    assert set(paths["/entities"]) == {"get"}


def test_detail_schema(app: FastAPI) -> None:
    schemas = app.openapi()["components"]["schemas"]

    assert set(schemas["EntityDetailRead"]["properties"]) == {"entity", "mention_count", "mentions"}
    assert set(schemas["EntityMentionRead"]["properties"]) == {
        "id",
        "document_id",
        "chunk_id",
        "surface_text",
        "entity_type",
        "start_char",
        "end_char",
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
        ({"query": "  "}, "query"),
        ({"query": "x" * 301}, "query"),
        ({"entity_type": ""}, "entity_type"),
        ({"limit": "0"}, "limit"),
        ({"offset": "-1"}, "offset"),
    ],
    ids=["blank query", "long query", "blank type", "zero limit", "negative offset"],
)
def test_bad_list_request(params: dict[str, str], field: str) -> None:
    status_code, body = get("/entities", params)

    assert status_code == 422
    assert body["error"]["details"][0]["loc"] == ["query", field]


def test_bad_entity_id() -> None:
    status_code, _ = get("/entities/not-a-uuid")

    assert status_code == 422


def test_needs_a_database(client: TestClient) -> None:
    assert client.get("/entities").status_code == 503
