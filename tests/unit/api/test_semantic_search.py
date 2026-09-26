from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"
VALID = {"q": "climate", "provider": "test", "model": "words-4"}


def test_semantic_search_route_is_in_openapi(app: FastAPI) -> None:
    get = app.openapi()["paths"]["/search/semantic"]["get"]
    parameters = {parameter["name"]: parameter for parameter in get["parameters"]}

    assert get["tags"] == ["Search"]
    for name in ["q", "provider", "model"]:
        assert parameters[name]["required"] is True
    assert parameters["provider"]["schema"]["maxLength"] == 50
    assert parameters["model"]["schema"]["maxLength"] == 100
    assert (parameters["limit"]["schema"]["minimum"], parameters["limit"]["schema"]["maximum"]) == (
        1,
        50,
    )
    assert parameters["source_id"]["required"] is False


def test_result_schema_has_no_vectors(app: FastAPI) -> None:
    schema = app.openapi()["components"]["schemas"]["SemanticSearchResultRead"]

    assert set(schema["properties"]) == {
        "document_id",
        "chunk_id",
        "source_id",
        "title",
        "url",
        "chunk_metadata",
        "similarity",
    }


def test_no_embedding_model_is_configured_by_default(app: FastAPI) -> None:
    assert app.state.embedding_providers.keys() == []


def get(params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.get("/search/semantic", params=params)
    body: dict[str, Any] = response.json()
    return response.status_code, body


@pytest.mark.parametrize(
    ("params", "field"),
    [
        (VALID | {"q": "   "}, "q"),
        (VALID | {"q": "x" * 501}, "q"),
        ({"q": "climate", "model": "words-4"}, "provider"),
        ({"q": "climate", "provider": "test"}, "model"),
        (VALID | {"provider": ""}, "provider"),
        (VALID | {"model": "m" * 101}, "model"),
        (VALID | {"limit": "0"}, "limit"),
        (VALID | {"limit": "51"}, "limit"),
        (VALID | {"source_id": "not-a-uuid"}, "source_id"),
    ],
    ids=[
        "blank query",
        "long query",
        "no provider",
        "no model",
        "empty provider",
        "long model",
        "limit too small",
        "limit too large",
        "bad source id",
    ],
)
def test_bad_request_is_rejected(params: dict[str, str], field: str) -> None:
    status_code, body = get(params)

    assert status_code == 422
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"][0]["loc"] == ["query", field]


def test_model_that_is_not_configured() -> None:
    status_code, body = get(VALID)

    assert status_code == 503
    assert body == {
        "error": {
            "code": "service_unavailable",
            "message": "Embedding model test/words-4 is not configured.",
        }
    }


def test_semantic_search_needs_a_database(client: TestClient) -> None:
    response = client.get("/search/semantic", params=VALID)

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Database is not configured."
