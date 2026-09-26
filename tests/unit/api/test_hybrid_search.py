from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"
VALID = {"q": "climate", "provider": "test", "model": "words-4"}


def test_hybrid_search_route_is_in_openapi(app: FastAPI) -> None:
    get = app.openapi()["paths"]["/search/hybrid"]["get"]
    parameters = {parameter["name"]: parameter for parameter in get["parameters"]}

    assert get["tags"] == ["Search"]
    for name in ["q", "provider", "model"]:
        assert parameters[name]["required"] is True
    assert (parameters["limit"]["schema"]["minimum"], parameters["limit"]["schema"]["maximum"]) == (
        1,
        50,
    )
    assert parameters["source_id"]["required"] is False


def test_result_schema(app: FastAPI) -> None:
    schema = app.openapi()["components"]["schemas"]["HybridSearchResultRead"]

    assert set(schema["properties"]) == {
        "document_id",
        "chunk_id",
        "source_id",
        "title",
        "url",
        "excerpt",
        "chunk_metadata",
        "lexical_rank",
        "vector_similarity",
        "hybrid_score",
    }


def get(params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.get("/search/hybrid", params=params)
    body: dict[str, Any] = response.json()
    return response.status_code, body


@pytest.mark.parametrize(
    ("params", "field"),
    [
        (VALID | {"q": "   "}, "q"),
        ({"q": "climate", "model": "words-4"}, "provider"),
        ({"q": "climate", "provider": "test"}, "model"),
        (VALID | {"limit": "0"}, "limit"),
        (VALID | {"limit": "51"}, "limit"),
        (VALID | {"source_id": "not-a-uuid"}, "source_id"),
    ],
    ids=[
        "blank query",
        "no provider",
        "no model",
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
