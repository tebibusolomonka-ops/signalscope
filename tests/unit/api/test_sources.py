import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, so any connection attempt would fail.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_sources_need_a_database(client: TestClient) -> None:
    create = client.post("/sources", json={"type": "upload", "name": "Uploads"})
    listing = client.get("/sources")

    for response in [create, listing]:
        assert response.status_code == 503
        assert response.json() == {
            "error": {"code": "service_unavailable", "message": "Database is not configured."},
        }


def test_invalid_source_id_is_rejected() -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app) as client:
        response = client.get("/sources/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["path", "source_id"]


def test_invalid_source_body_is_rejected() -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app) as client:
        response = client.post("/sources", json={"type": "podcast", "name": "Example"})

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["body", "type"]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_invalid_page_params_are_rejected(params: dict[str, int]) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app) as client:
        response = client.get("/sources", params=params)

    assert response.status_code == 422


def test_source_routes_are_in_openapi(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    assert set(paths["/sources"]) == {"get", "post"}
    assert set(paths["/sources/{source_id}"]) == {"get", "delete"}
    assert paths["/sources"]["post"]["tags"] == ["Sources"]
