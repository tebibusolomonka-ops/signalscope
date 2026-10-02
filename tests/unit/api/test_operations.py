import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these requests fail before any query runs.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_overview_is_in_openapi(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    schemas = app.openapi()["components"]["schemas"]

    parameters = paths["/operations/overview"]["get"]["parameters"]
    assert [(item["name"], item["required"]) for item in parameters] == [("organization_id", True)]
    assert set(schemas["OperationsOverviewRead"]["properties"]) == {"organization", "queues"}
    assert set(schemas["QueueSummaryRead"]["properties"]) == {
        "queue",
        "pending_count",
        "running_count",
        "failed_count",
        "oldest_pending_at",
        "oldest_failed_at",
    }
    assert schemas["OperationsQueue"]["enum"] == [
        "ingestion",
        "processing",
        "embedding",
        "entity_extraction",
        "event_extraction",
        "claim_extraction",
    ]


@pytest.mark.parametrize("query", ["", "?organization_id=nope"])
def test_overview_needs_a_valid_organization(query: str) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app) as client:
        response = client.get(f"/operations/overview{query}")

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["query", "organization_id"]


def test_overview_needs_a_database(client: TestClient) -> None:
    response = client.get(f"/operations/overview?organization_id={uuid.uuid4()}")

    assert response.status_code == 503


def test_failed_jobs_are_in_openapi(app: FastAPI) -> None:
    operation = app.openapi()["paths"]["/operations/jobs"]["get"]

    assert {item["name"] for item in operation["parameters"]} == {
        "organization_id",
        "queue",
        "status",
        "limit",
        "offset",
    }
    schemas = app.openapi()["components"]["schemas"]
    assert set(schemas["OperationsJobRead"]["properties"]) == {
        "queue",
        "job_id",
        "status",
        "resource_type",
        "resource_id",
        "provider",
        "model",
        "attempt_count",
        "available_at",
        "created_at",
        "finished_at",
        "error",
    }


def test_operation_history_is_in_openapi(app: FastAPI) -> None:
    operation = app.openapi()["paths"]["/operations/history"]["get"]
    schemas = app.openapi()["components"]["schemas"]

    assert {item["name"] for item in operation["parameters"]} == {
        "organization_id",
        "queue",
        "outcome",
        "resource_type",
        "resource_id",
        "created_from",
        "created_to",
        "limit",
        "offset",
    }
    assert set(schemas["OperationAttemptRead"]["properties"]) == {
        "id",
        "organization_id",
        "queue_name",
        "job_id",
        "attempt_number",
        "resource_type",
        "resource_id",
        "started_at",
        "finished_at",
        "outcome",
        "safe_error",
        "created_at",
    }


@pytest.mark.parametrize(
    ("query", "field"),
    [("queue=blob_cleanup", "queue"), ("status=pending", "status"), ("limit=0", "limit")],
)
def test_failed_jobs_refuse_unknown_values(query: str, field: str) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app) as client:
        response = client.get(f"/operations/jobs?organization_id={uuid.uuid4()}&{query}")

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["query", field]


def test_retry_is_in_openapi(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    schemas = app.openapi()["components"]["schemas"]

    assert set(paths["/operations/jobs/{queue}/{job_id}/retry"]) == {"post"}
    assert set(schemas["JobRetryRequest"]["properties"]) == {"organization_id"}


@pytest.mark.parametrize(
    ("path", "body", "location"),
    [
        (
            f"/operations/jobs/blob_cleanup/{uuid.uuid4()}/retry",
            {"organization_id": str(uuid.uuid4())},
            ["path", "queue"],
        ),
        (
            "/operations/jobs/embedding/nope/retry",
            {"organization_id": str(uuid.uuid4())},
            ["path", "job_id"],
        ),
        (f"/operations/jobs/embedding/{uuid.uuid4()}/retry", {}, ["body", "organization_id"]),
    ],
)
def test_retry_refuses_bad_input(path: str, body: dict[str, str], location: list[str]) -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app) as client:
        response = client.post(path, json=body)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == location
