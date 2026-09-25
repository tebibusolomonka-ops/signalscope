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
    assert set(paths["/sources/{source_id}/schedule"]) == {"put", "delete"}
    assert paths["/sources"]["post"]["tags"] == ["Sources"]
    assert paths["/sources/{source_id}/schedule"]["put"]["tags"] == ["Sources"]


def test_schedule_schema_is_in_openapi(app: FastAPI) -> None:
    openapi = app.openapi()
    put = openapi["paths"]["/sources/{source_id}/schedule"]["put"]
    schema = openapi["components"]["schemas"]["SourceScheduleUpdate"]

    assert put["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SourceScheduleUpdate"
    }
    assert put["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SourceRead"
    }
    assert schema["required"] == ["interval_minutes"]
    assert schema["properties"]["interval_minutes"]["minimum"] == 1
    assert schema["properties"]["interval_minutes"]["maximum"] == 10080


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, "interval_minutes"),
        ({"interval_minutes": 0}, "interval_minutes"),
        ({"interval_minutes": 10081}, "interval_minutes"),
        ({"interval_minutes": "often"}, "interval_minutes"),
        ({"interval_minutes": 60, "start_at": "2026-06-01T08:30:00"}, "start_at"),
        ({"interval_minutes": 60, "enabled": True}, "enabled"),
    ],
)
def test_invalid_schedule_is_rejected(body: dict[str, object], field: str) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app) as client:
        response = client.put("/sources/00000000-0000-0000-0000-000000000001/schedule", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["body", field]
