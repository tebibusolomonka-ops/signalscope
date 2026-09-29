from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_routes_are_in_openapi(app: FastAPI) -> None:
    openapi = app.openapi()
    paths = openapi["paths"]

    assert set(paths["/auth/login"]) == {"post"}
    assert set(paths["/auth/logout"]) == {"post"}
    assert set(paths["/auth/me"]) == {"get"}
    assert set(paths["/auth/sessions"]) == {"get"}
    assert set(paths["/auth/sessions/{session_id}"]) == {"delete"}
    assert set(paths["/auth/logout-all"]) == {"post"}
    assert set(paths["/auth/change-password"]) == {"post"}
    assert paths["/auth/change-password"]["post"]["security"] == [{"HTTPBearer": []}]
    session = openapi["components"]["schemas"]["SessionRead"]["properties"]
    assert not any("token" in name or "hash" in name for name in session)
    assert "current_session" in session
    # There is no self registration.
    assert not any("register" in path for path in paths)
    assert openapi["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    assert paths["/auth/me"]["get"]["security"] == [{"HTTPBearer": []}]
    assert paths["/auth/logout"]["post"]["security"] == [{"HTTPBearer": []}]
    assert "security" not in paths["/auth/login"]["post"]
    user = openapi["components"]["schemas"]["UserRead"]["properties"]
    assert not any("password" in name or "hash" in name for name in user)
    assert set(openapi["components"]["schemas"]["LoginResponse"]["properties"]) == {
        "access_token",
        "token_type",
        "expires_at",
        "user",
    }


def call(
    method: str, path: str, *, auth_enabled: bool, **options: Any
) -> tuple[int, dict[str, Any], dict[str, str]]:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL, auth_enabled=auth_enabled))
    with TestClient(app) as client:
        response = client.request(method, path, **options)
    body: dict[str, Any] = response.json()
    return response.status_code, body, dict(response.headers)


@pytest.mark.parametrize(
    ("method", "path", "options"),
    [
        ("POST", "/auth/login", {"json": {"email": "a@b.org", "password": "x" * 12}}),
        ("GET", "/auth/me", {"headers": {"Authorization": "Bearer abc"}}),
        ("POST", "/auth/logout", {}),
        ("GET", "/auth/sessions", {}),
        ("POST", "/auth/logout-all", {}),
    ],
    ids=["login", "me", "logout", "sessions", "logout all"],
)
def test_auth_disabled_answers_503(method: str, path: str, options: dict[str, Any]) -> None:
    status_code, body, _ = call(method, path, auth_enabled=False, **options)

    assert status_code == 503
    assert body["error"]["message"] == (
        "Authentication is not enabled. Set SIGNALSCOPE_AUTH_ENABLED=true."
    )


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer"}],
    ids=["missing", "other scheme", "empty token"],
)
def test_missing_token_is_401(headers: dict[str, str]) -> None:
    status_code, body, response_headers = call(
        "GET", "/auth/me", auth_enabled=True, headers=headers
    )

    assert status_code == 401
    assert body["error"] == {
        "code": "unauthenticated",
        "message": "Authentication is required.",
    }
    assert response_headers["www-authenticate"] == "Bearer"


def test_auth_is_off_by_default() -> None:
    assert Settings().auth_enabled is False
