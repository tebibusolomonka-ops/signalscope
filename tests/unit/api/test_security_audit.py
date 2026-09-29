import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_route_is_in_openapi(app: FastAPI) -> None:
    get = app.openapi()["paths"]["/security/audit"]["get"]

    assert {parameter["name"] for parameter in get["parameters"]} == {
        "organization_id",
        "actor_user_id",
        "action",
        "resource_type",
        "resource_id",
        "created_from",
        "created_to",
        "limit",
        "offset",
    }
    assert get["security"] == [{"HTTPBearer": []}]


@pytest.mark.parametrize(("enabled", "expected"), [(False, 503), (True, 401)])
def test_needs_auth(enabled: bool, expected: int) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL, auth_enabled=enabled))
    with TestClient(app) as client:
        assert client.get("/security/audit").status_code == expected
