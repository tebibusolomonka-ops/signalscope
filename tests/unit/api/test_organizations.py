import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"
ORGANIZATION = f"/organizations/{uuid.uuid4()}"


def test_routes_are_in_openapi(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    assert set(paths["/organizations"]) == {"get", "post"}
    assert set(paths["/organizations/{organization_id}"]) == {"get"}
    assert set(paths["/organizations/{organization_id}/members"]) == {"get", "post"}
    assert set(paths["/organizations/{organization_id}/members/{user_id}"]) == {
        "patch",
        "delete",
    }
    for methods in (
        paths["/organizations"],
        paths["/organizations/{organization_id}/members/{user_id}"],
    ):
        for operation in methods.values():
            assert operation["security"] == [{"HTTPBearer": []}]
    assert set(paths["/organizations/{organization_id}/access-summary"]) == {"get"}
    assert set(paths["/organizations/{organization_id}/exports"]) == {"get", "post"}
    assert set(paths["/organizations/{organization_id}/exports/{export_id}"]) == {"get"}
    assert set(paths["/organizations/{organization_id}/exports/{export_id}/download"]) == {"get"}
    export = app.openapi()["components"]["schemas"]["OrganizationExportRead"]
    assert "artifact_key" not in export["properties"]
    summary = app.openapi()["components"]["schemas"]["OrganizationAccessSummaryRead"]
    assert set(summary["properties"]) == {
        "organization",
        "members",
        "member_status",
        "invitations",
        "investigations",
        "collaborators",
    }
    roles = app.openapi()["components"]["schemas"]["OrganizationRole"]["enum"]
    assert roles == ["owner", "admin", "member", "viewer"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/organizations"),
        ("POST", "/organizations"),
        ("GET", f"{ORGANIZATION}/members"),
        ("DELETE", f"{ORGANIZATION}/members/{uuid.uuid4()}"),
        ("GET", f"{ORGANIZATION}/access-summary"),
        ("GET", f"{ORGANIZATION}/exports"),
    ],
)
def test_needs_auth_enabled(method: str, path: str) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.request(method, path, json={"name": "News", "slug": "news"})

    assert response.status_code == 503
    assert "SIGNALSCOPE_AUTH_ENABLED" in response.json()["error"]["message"]


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/organizations"), ("GET", f"{ORGANIZATION}/members")],
)
def test_needs_a_token(method: str, path: str) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL, auth_enabled=True))
    with TestClient(app) as client:
        response = client.request(method, path)

    assert response.status_code == 401
