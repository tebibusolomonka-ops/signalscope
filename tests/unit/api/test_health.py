from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings


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


def test_version_returns_safe_build_metadata() -> None:
    secret = "postgresql+asyncpg://user:secret@database/signalscope"
    app = create_app(
        Settings(
            build_sha="abc123",
            build_time="2026-10-05T10:00:00Z",
            release_name="October release",
            database_url=secret,
        )
    )

    response = TestClient(app).get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "application_version": "0.1.0",
        "python_version": response.json()["python_version"],
        "build_sha": "abc123",
        "build_time": "2026-10-05T10:00:00Z",
        "release_name": "October release",
    }
    assert secret not in response.text


def test_openapi_lists_health_endpoints(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/version" in paths
