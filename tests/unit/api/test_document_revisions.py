import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"
DOCUMENT_ID = "00000000-0000-0000-0000-000000000001"


def test_revision_routes_are_read_only(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    assert set(paths["/documents/{document_id}/revisions"]) == {"get"}
    assert set(paths["/documents/{document_id}/revisions/{version}"]) == {"get"}
    assert paths["/documents/{document_id}/revisions"]["get"]["tags"] == ["Documents"]


def test_list_leaves_out_the_text(app: FastAPI) -> None:
    schemas = app.openapi()["components"]["schemas"]

    assert "content" not in schemas["DocumentRevisionSummary"]["properties"]
    assert "content_length" in schemas["DocumentRevisionSummary"]["properties"]
    assert {"content", "parser_metadata"} <= set(schemas["DocumentRevisionRead"]["properties"])


@pytest.mark.parametrize(
    ("path", "field"),
    [
        (f"/documents/{DOCUMENT_ID}/revisions/0", "version"),
        (f"/documents/{DOCUMENT_ID}/revisions/first", "version"),
        ("/documents/not-a-uuid/revisions", "document_id"),
    ],
)
def test_bad_path_values_are_rejected(path: str, field: str) -> None:
    with TestClient(create_app(Settings(database_url=FAKE_DATABASE_URL))) as client:
        response = client.get(path)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["path", field]


def test_revisions_need_a_database(client: TestClient) -> None:
    response = client.get(f"/documents/{DOCUMENT_ID}/revisions")

    assert response.status_code == 503
