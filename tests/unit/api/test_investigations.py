import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_routes_are_in_openapi(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    schemas = app.openapi()["components"]["schemas"]

    assert set(paths["/investigations"]) == {"get", "post"}
    assert set(paths["/investigations/{investigation_id}"]) == {"get", "patch", "delete"}
    assert set(paths["/investigations/{investigation_id}/items"]) == {"get", "post"}
    assert set(paths["/investigations/{investigation_id}/items/{item_id}"]) == {"delete"}
    assert {parameter["name"] for parameter in paths["/investigations"]["get"]["parameters"]} == {
        "status",
        "limit",
        "offset",
    }
    # No owner: there are no users yet.
    assert set(schemas["InvestigationRead"]["properties"]) == {
        "id",
        "title",
        "description",
        "status",
        "created_at",
        "updated_at",
    }
    assert schemas["InvestigationItemType"]["enum"] == [
        "source",
        "document",
        "event",
        "event_cluster",
        "entity",
        "claim",
        "research_session",
    ]


def send(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.request(method, path, json=body)
    result: dict[str, Any] = response.json()
    return response.status_code, result


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/investigations", {}),
        ("POST", "/investigations", {"title": " "}),
        ("POST", "/investigations", {"title": "x" * 201}),
        ("POST", "/investigations", {"title": "Floods", "owner": "me"}),
        ("PATCH", f"/investigations/{uuid.uuid4()}", {"status": "archived"}),
        (
            "POST",
            f"/investigations/{uuid.uuid4()}/items",
            {"item_type": "graph", "reference_id": str(uuid.uuid4())},
        ),
        (
            "POST",
            f"/investigations/{uuid.uuid4()}/items",
            {"item_type": "event", "reference_id": "x"},
        ),
        ("GET", "/investigations/not-a-uuid", None),
    ],
    ids=[
        "no title",
        "blank title",
        "long title",
        "unknown field",
        "bad status",
        "bad item type",
        "bad reference",
        "bad id",
    ],
)
def test_bad_requests(method: str, path: str, body: dict[str, Any] | None) -> None:
    status_code, _ = send(method, path, body)

    assert status_code == 422


def test_bad_status_filter() -> None:
    status_code, result = send("GET", "/investigations?status=archived")

    assert status_code == 422
    assert result["error"]["details"][0]["loc"] == ["query", "status"]


def test_needs_a_database(client: TestClient) -> None:
    assert client.get("/investigations").status_code == 503


def test_save_research_session_route_is_in_openapi(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    assert set(paths["/investigations/{investigation_id}/research-sessions/{session_id}"]) == {
        "post"
    }


def test_export_route_is_in_openapi(app: FastAPI) -> None:
    get = app.openapi()["paths"]["/investigations/{investigation_id}/export"]["get"]

    assert [parameter["name"] for parameter in get["parameters"]] == ["investigation_id", "format"]
    assert set(get["responses"]["200"]["content"]) == {"application/json", "text/markdown"}
    schema = app.openapi()["components"]["schemas"]["ExportedItem"]
    assert "current_reference_exists" in schema["properties"]


def test_export_bad_format() -> None:
    status_code, result = send("GET", f"/investigations/{uuid.uuid4()}/export?format=pdf")

    assert status_code == 422
    assert result["error"]["details"][0]["loc"] == ["query", "format"]
