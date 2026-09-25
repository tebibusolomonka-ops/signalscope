import uuid

import pytest
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
    assert response.json()["error"]["details"][0]["loc"] == ["path", "document_id"]


def test_invalid_document_body_is_rejected() -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app) as client:
        response = client.post(
            "/documents",
            json={"source_id": str(uuid.uuid4()), "published_at": "2026-03-01T12:00:00"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["body", "published_at"]


def test_document_routes_are_in_openapi(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    assert set(paths["/documents"]) == {"get", "post"}
    assert set(paths["/documents/{document_id}"]) == {"get", "delete"}
    assert paths["/documents"]["post"]["tags"] == ["Documents"]


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"source_id": "not-a-uuid"}, "source_id"),
        ({"published_from": "2026-03-01T10:00:00"}, "published_from"),
        ({"published_to": "soon"}, "published_to"),
    ],
)
def test_invalid_filters_are_rejected(params: dict[str, str], field: str) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app) as client:
        response = client.get("/documents", params=params)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["query", field]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_invalid_page_params_are_rejected(params: dict[str, int]) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app) as client:
        response = client.get("/documents", params=params)

    assert response.status_code == 422


def test_blank_language_filter_is_rejected() -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app) as client:
        response = client.get("/documents", params={"language": "  "})

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["query", "language"]
