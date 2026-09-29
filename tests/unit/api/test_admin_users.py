import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"
ROUTES = [
    ("GET", "/admin/users"),
    ("POST", "/admin/users"),
    ("GET", f"/admin/users/{uuid.uuid4()}"),
    ("PATCH", f"/admin/users/{uuid.uuid4()}/status"),
    ("GET", f"/admin/users/{uuid.uuid4()}/sessions"),
    ("POST", f"/admin/users/{uuid.uuid4()}/revoke-sessions"),
]


def test_routes_are_in_openapi(app: FastAPI) -> None:
    openapi = app.openapi()
    paths = openapi["paths"]

    assert set(paths["/admin/users"]) == {"get", "post"}
    assert set(paths["/admin/users/{user_id}"]) == {"get"}
    assert set(paths["/admin/users/{user_id}/status"]) == {"patch"}
    assert set(paths["/admin/users/{user_id}/sessions"]) == {"get"}
    assert set(paths["/admin/users/{user_id}/sessions/{session_id}"]) == {"delete"}
    assert set(paths["/admin/users/{user_id}/revoke-sessions"]) == {"post"}
    session = openapi["components"]["schemas"]["AdminSessionRead"]["properties"]
    assert not any("token" in name or "hash" in name for name in session)
    parameters = {item["name"] for item in paths["/admin/users"]["get"]["parameters"]}
    assert parameters == {"query", "is_active", "is_system_admin", "limit", "offset"}
    for schema in ("AdminUserRead", "AdminUserCreate"):
        fields = openapi["components"]["schemas"][schema]["properties"]
        assert not any("hash" in name or "token" in name for name in fields)
    assert "password" not in openapi["components"]["schemas"]["AdminUserRead"]["properties"]


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_needs_auth_enabled(method: str, path: str) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.request(method, path)

    assert response.status_code == 503
    assert "SIGNALSCOPE_AUTH_ENABLED" in response.json()["error"]["message"]


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_needs_a_token(method: str, path: str) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL, auth_enabled=True))
    with TestClient(app) as client:
        response = client.request(method, path)

    assert response.status_code == 401
