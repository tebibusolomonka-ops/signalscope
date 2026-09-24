from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings


def test_health_returns_ok() -> None:
    client = TestClient(create_app(Settings()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok"}
