import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, so any connection attempt would fail.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_documents_need_a_database(client: TestClient) -> None:
    create = client.post("/documents", json={"source_id": str(uuid.uuid4())})
    listing = client.get("/documents")

    for response in [create, listing]:
        assert response.status_code == 503
        assert response.json() == {
            "error": {"code": "service_unavailable", "message": "Database is not configured."},
        }


def test_invalid_document_id_is_rejected() -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app) as client:
        response = client.get("/documents/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "document_id"]


def test_invalid_document_body_is_rejected() -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app) as client:
        response = client.post(
            "/documents",
            json={"source_id": str(uuid.uuid4()), "published_at": "2026-03-01T12:00:00"},
        )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "published_at"]


def test_document_routes_are_in_openapi(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    assert set(paths["/documents"]) == {"get", "post"}
    assert set(paths["/documents/{document_id}"]) == {"get", "delete"}
    assert paths["/documents"]["post"]["tags"] == ["Documents"]
