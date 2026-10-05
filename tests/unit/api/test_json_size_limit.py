import json

from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings

LIMIT = 1024


def client() -> TestClient:
    return TestClient(create_app(Settings(max_json_request_bytes=LIMIT)))


def json_body(size: int) -> bytes:
    payload = {"value": "x" * size}
    return json.dumps(payload).encode()


def test_json_over_limit_is_rejected_with_413() -> None:
    body = json_body(LIMIT * 2)
    response = client().post(
        "/auth/login", content=body, headers={"content-type": "application/json"}
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    # The rejection still carries the security headers.
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_json_at_or_under_limit_passes_the_middleware() -> None:
    small = json.dumps({"email": "a@b.co", "password": "x"}).encode()
    assert len(small) <= LIMIT
    response = client().post(
        "/auth/login", content=small, headers={"content-type": "application/json"}
    )

    # Reaches routing (auth disabled answers 503), not blocked by the size limit.
    assert response.status_code != 413


def test_get_requests_are_not_limited() -> None:
    response = client().get("/health")
    assert response.status_code == 200


def test_non_json_bodies_are_not_limited() -> None:
    # A large non-JSON body (like an archive upload) is not blocked here.
    big = b"x" * (LIMIT * 4)
    response = client().post(
        "/organizations/x/restore", content=big, headers={"content-type": "application/zip"}
    )

    assert response.status_code != 413
