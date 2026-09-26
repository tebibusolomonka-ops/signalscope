from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_route_is_in_openapi(app: FastAPI) -> None:
    get = app.openapi()["paths"]["/search/reranked"]["get"]
    parameters = {parameter["name"]: parameter for parameter in get["parameters"]}

    assert get["tags"] == ["Search"]
    assert set(parameters) == {"q", "limit", "source_id"}
    assert parameters["q"]["required"] is True
    assert (parameters["limit"]["schema"]["minimum"], parameters["limit"]["schema"]["maximum"]) == (
        1,
        50,
    )


def test_result_schema_has_no_chunk_text(app: FastAPI) -> None:
    schema = app.openapi()["components"]["schemas"]["RerankedSearchResultRead"]

    assert set(schema["properties"]) == {
        "document_id",
        "chunk_id",
        "source_id",
        "title",
        "url",
        "excerpt",
        "chunk_metadata",
        "hybrid_score",
        "reranker_score",
    }


def get(params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.get("/search/reranked", params=params)
    body: dict[str, Any] = response.json()
    return response.status_code, body


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"q": "  "}, "q"),
        ({}, "q"),
        ({"q": "wind", "limit": "0"}, "limit"),
        ({"q": "wind", "limit": "51"}, "limit"),
        ({"q": "wind", "source_id": "nope"}, "source_id"),
    ],
    ids=["blank query", "no query", "limit too small", "limit too large", "bad source id"],
)
def test_bad_request_is_rejected(params: dict[str, str], field: str) -> None:
    status_code, body = get(params)

    assert status_code == 422
    assert body["error"]["details"][0]["loc"] == ["query", field]


def test_reranker_that_is_not_configured() -> None:
    status_code, body = get({"q": "wind"})

    assert status_code == 503
    assert body == {
        "error": {
            "code": "service_unavailable",
            "message": (
                "Reranker sentence_transformers/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 "
                "is not configured."
            ),
        }
    }
