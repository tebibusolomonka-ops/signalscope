from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_route_is_in_openapi(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    schemas = app.openapi()["components"]["schemas"]

    assert set(paths["/timeline"]) == {"get"}
    assert {parameter["name"] for parameter in paths["/timeline"]["get"]["parameters"]} == {
        "occurred_from",
        "occurred_to",
        "event_type",
        "source_id",
        "order",
        "limit",
        "offset",
        "organization_id",
    }
    # A summary per cluster. Evidence rows are not listed.
    assert set(schemas["TimelineItemRead"]["properties"]) == {
        "cluster_id",
        "event_type",
        "title",
        "occurred_at",
        "event_count",
        "source_count",
        "evidence_count",
        "sources",
    }
    assert schemas["TimelineOrder"]["enum"] == ["newest_first", "oldest_first"]


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"source_id": "not-a-uuid"}, "source_id"),
        ({"occurred_from": "yesterday"}, "occurred_from"),
        ({"occurred_to": "2026-09-01T00:00:00"}, "occurred_to"),
        ({"event_type": " "}, "event_type"),
        ({"order": "importance"}, "order"),
        ({"limit": "0"}, "limit"),
    ],
    ids=["bad source", "not a time", "time without zone", "blank type", "bad order", "limit"],
)
def test_bad_request(params: dict[str, Any], field: str) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.get("/timeline", params=params)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["query", field]


def test_needs_a_database(client: TestClient) -> None:
    assert client.get("/timeline").status_code == 503


def test_cluster_detail_route_is_in_openapi(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    schemas = app.openapi()["components"]["schemas"]

    # Read only: no merge or split.
    assert set(paths["/event-clusters/{cluster_id}"]) == {"get"}
    assert set(schemas["EventClusterDetailRead"]["properties"]) == {
        "cluster_id",
        "event_type",
        "title",
        "occurred_at",
        "event_count",
        "source_count",
        "evidence_count",
        "members",
    }
    assert "text" not in schemas["ClusterEvidenceRead"]["properties"]


def test_cluster_detail_bad_id() -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))
    with TestClient(app) as client:
        response = client.get("/event-clusters/not-a-uuid")

    assert response.status_code == 422
