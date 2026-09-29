import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"
INVITATIONS = f"/organizations/{uuid.uuid4()}/invitations"


def test_routes_are_in_openapi(app: FastAPI) -> None:
    openapi = app.openapi()
    paths = openapi["paths"]
    schemas = openapi["components"]["schemas"]

    assert set(paths["/organizations/{organization_id}/invitations"]) == {"get", "post"}
    assert set(paths["/organizations/{organization_id}/invitations/{invitation_id}"]) == {"delete"}
    assert schemas["InvitationRole"]["enum"] == ["admin", "member", "viewer"]
    assert schemas["InvitationStatus"]["enum"] == ["pending", "accepted", "revoked", "expired"]
    assert not any("token" in name for name in schemas["InvitationRead"]["properties"])
    assert set(schemas["InvitationCreated"]["properties"]) == {"invitation", "invitation_token"}
    assert set(paths["/organization-invitations/accept"]) == {"post"}


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_needs_auth(method: str) -> None:
    for enabled, expected in ((False, 503), (True, 401)):
        app = create_app(Settings(database_url=FAKE_DATABASE_URL, auth_enabled=enabled))
        with TestClient(app) as client:
            response = client.request(method, INVITATIONS, json={"email": "a@example.org"})
        assert response.status_code == expected
