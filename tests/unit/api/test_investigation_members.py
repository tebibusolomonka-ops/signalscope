import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"
MEMBERS = f"/investigations/{uuid.uuid4()}/members"


def test_routes_are_in_openapi(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    assert set(paths["/investigations/{investigation_id}/members"]) == {"get", "post"}
    assert set(paths["/investigations/{investigation_id}/members/{user_id}"]) == {
        "patch",
        "delete",
    }
    schemas = app.openapi()["components"]["schemas"]
    assert schemas["CollaboratorRole"]["enum"] == ["owner", "editor", "viewer"]
    assert schemas["CollaboratorCreate"]["properties"]["role"]["default"] == "viewer"


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", MEMBERS), ("POST", MEMBERS), ("DELETE", f"{MEMBERS}/{uuid.uuid4()}")],
)
def test_needs_auth_enabled(method: str, path: str) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.request(method, path, json={"user_id": str(uuid.uuid4())})

    assert response.status_code == 503
    assert "SIGNALSCOPE_AUTH_ENABLED" in response.json()["error"]["message"]


def test_needs_a_token() -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL, auth_enabled=True))
    with TestClient(app) as client:
        response = client.get(MEMBERS)

    assert response.status_code == 401
