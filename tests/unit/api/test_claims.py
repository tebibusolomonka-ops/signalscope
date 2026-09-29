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

    assert {parameter["name"] for parameter in paths["/claims"]["get"]["parameters"]} == {
        "query",
        "claim_type",
        "limit",
        "offset",
        "organization_id",
    }
    # Claims come from extraction, so there is no way to write them.
    assert set(paths["/claims"]) == {"get"}
    assert set(paths["/claims/{claim_id}"]) == {"get"}
    assert "evidence_count" in schemas["ClaimRead"]["properties"]
    assert set(schemas["ClaimEvidenceRead"]["properties"]) == {
        "id",
        "document_id",
        "chunk_id",
        "surface_text",
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
    [({"query": " "}, "query"), ({"claim_type": ""}, "claim_type"), ({"offset": "-1"}, "offset")],
    ids=["blank query", "blank type", "negative offset"],
)
def test_bad_request(params: dict[str, str], field: str) -> None:
    status_code, body = get("/claims", params)

    assert status_code == 422
    assert body["error"]["details"][0]["loc"] == ["query", field]


def test_needs_a_database(client: TestClient) -> None:
    assert client.get("/claims").status_code == 503


def test_coverage_route_is_in_openapi(app: FastAPI) -> None:
    get = app.openapi()["paths"]["/claims/coverage"]["get"]
    schema = app.openapi()["components"]["schemas"]["ClaimCoverageRead"]

    assert [parameter["name"] for parameter in get["parameters"]] == [
        "organization_id",
        "document_id",
    ]
    assert set(schema["properties"]) == {
        "provider",
        "model",
        "document_id",
        "chunk_count",
        "extracted_count",
        "pending_count",
        "failed_count",
        "coverage_ratio",
    }


def test_coverage_needs_a_database(client: TestClient) -> None:
    assert client.get("/claims/coverage").status_code == 503


def test_coverage_is_not_read_as_a_claim_id() -> None:
    status_code, body = get("/claims/coverage", {"document_id": "not-a-uuid"})

    assert status_code == 422
    assert body["error"]["details"][0]["loc"] == ["query", "document_id"]
