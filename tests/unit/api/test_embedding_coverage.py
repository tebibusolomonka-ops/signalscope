import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_route_is_in_openapi(app: FastAPI) -> None:
    get = app.openapi()["paths"]["/embeddings/coverage"]["get"]
    parameters = {parameter["name"]: parameter for parameter in get["parameters"]}

    assert get["tags"] == ["Embeddings"]
    assert list(parameters) == ["document_id"]
    assert parameters["document_id"]["required"] is False


def test_response_schema(app: FastAPI) -> None:
    schema = app.openapi()["components"]["schemas"]["EmbeddingCoverageRead"]

    assert set(schema["properties"]) == {
        "provider",
        "model",
        "document_id",
        "chunk_count",
        "embedded_count",
        "pending_count",
        "failed_count",
        "coverage",
    }


def test_needs_a_database(client: TestClient) -> None:
    response = client.get("/embeddings/coverage")

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Database is not configured."


@pytest.mark.parametrize("document_id", ["not-a-uuid", "12"])
def test_bad_document_id(document_id: str) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.get("/embeddings/coverage", params={"document_id": document_id})

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["query", "document_id"]
