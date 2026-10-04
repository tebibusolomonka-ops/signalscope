from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok"}


def test_liveness_answers_without_a_database(client: TestClient) -> None:
    # The client app has no database configured, yet liveness still answers.
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_without_a_database_is_unavailable(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 503


def test_openapi_lists_health_endpoints(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    assert "/health/live" in paths
    assert "/health/ready" in paths
