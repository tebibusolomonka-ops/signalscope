from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.errors import InvalidInputError
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_search_route_is_in_openapi(app: FastAPI) -> None:
    openapi = app.openapi()
    get = openapi["paths"]["/search"]["get"]
    parameters = {parameter["name"]: parameter for parameter in get["parameters"]}

    assert get["tags"] == ["Search"]
    assert parameters["q"]["required"] is True
    assert (parameters["q"]["schema"]["minLength"], parameters["q"]["schema"]["maxLength"]) == (
        1,
        500,
    )
    assert parameters["limit"]["schema"] == {
        "type": "integer",
        "maximum": 50,
        "minimum": 1,
        "default": 10,
        "title": "Limit",
    }
    assert parameters["source_id"]["required"] is False
    assert get["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SearchResponse"
    }


def test_result_schema_has_no_full_text(app: FastAPI) -> None:
    schema = app.openapi()["components"]["schemas"]["SearchResultRead"]

    assert set(schema["properties"]) == {
        "document_id",
        "chunk_id",
        "source_id",
        "title",
        "url",
        "excerpt",
        "rank",
    }


def get(params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.get("/search", params=params)
    body: dict[str, Any] = response.json()
    return response.status_code, body


@pytest.mark.parametrize("q", ["", "   ", "\t\n"])
def test_blank_query_is_rejected(q: str) -> None:
    status_code, body = get({"q": q})

    assert status_code == 422
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"][0]["loc"] == ["query", "q"]


def test_missing_query_is_rejected() -> None:
    status_code, body = get({})

    assert status_code == 422
    assert body["error"]["details"][0]["loc"] == ["query", "q"]


def test_long_query_is_rejected() -> None:
    status_code, body = get({"q": "x" * 501})

    assert status_code == 422
    assert body["error"]["details"][0]["loc"] == ["query", "q"]


@pytest.mark.parametrize("limit", ["0", "51", "-1", "many"])
def test_bad_limit_is_rejected(limit: str) -> None:
    status_code, body = get({"q": "climate", "limit": limit})

    assert status_code == 422
    assert body["error"]["details"][0]["loc"] == ["query", "limit"]


def test_bad_source_id_is_rejected() -> None:
    status_code, body = get({"q": "climate", "source_id": "not-a-uuid"})

    assert status_code == 422
    assert body["error"]["details"][0]["loc"] == ["query", "source_id"]


def test_search_needs_a_database(client: TestClient) -> None:
    response = client.get("/search", params={"q": "climate"})

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "service_unavailable", "message": "Database is not configured."},
    }


def test_invalid_input_error_returns_422(
    create_failing_app: Callable[[Exception], FastAPI],
) -> None:
    client = TestClient(create_failing_app(InvalidInputError("Search query must not be empty.")))

    response = client.get("/fail")

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "invalid_input", "message": "Search query must not be empty."},
    }
