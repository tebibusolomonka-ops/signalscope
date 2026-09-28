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

    for path in ("/dashboard/overview", "/dashboard/sources", "/dashboard/events"):
        assert set(paths[path]) == {"get"}
    assert [
        parameter["name"] for parameter in paths["/dashboard/sources"]["get"]["parameters"]
    ] == [
        "days",
        "source_id",
    ]
    assert [parameter["name"] for parameter in paths["/dashboard/events"]["get"]["parameters"]] == [
        "days",
        "event_type",
        "source_id",
    ]
    assert set(schemas["EventActivityDayRead"]["properties"]) == {
        "date",
        "events",
        "clusters",
        "cross_source_clusters",
    }
    # Aggregates only: no scores or rankings anywhere in the dashboard.
    for name in ("DashboardOverviewRead", "SourceActivityRead", "EventActivityRead"):
        fields = " ".join(schemas[name]["properties"]).lower()
        assert not any(word in fields for word in ("score", "rank", "trust", "credib"))


@pytest.mark.parametrize(
    ("path", "params", "field"),
    [
        ("/dashboard/sources", {"days": "0"}, "days"),
        ("/dashboard/sources", {"days": "366"}, "days"),
        ("/dashboard/sources", {"source_id": "not-a-uuid"}, "source_id"),
        ("/dashboard/events", {"days": "400"}, "days"),
        ("/dashboard/events", {"source_id": "x"}, "source_id"),
        ("/dashboard/events", {"event_type": " "}, "event_type"),
    ],
    ids=["zero days", "too many days", "bad source", "event days", "event source", "blank type"],
)
def test_bad_requests(path: str, params: dict[str, Any], field: str) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.get(path, params=params)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["query", field]


def test_needs_a_database(client: TestClient) -> None:
    assert client.get("/dashboard/overview").status_code == 503
