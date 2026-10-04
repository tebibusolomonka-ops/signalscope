import pytest
from fastapi.testclient import TestClient

from signalscope.api.middleware import SECURITY_HEADERS

EXPECTED = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def test_expected_header_values() -> None:
    assert SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"
    assert SECURITY_HEADERS["Referrer-Policy"] == "no-referrer"
    assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"
    assert "camera=()" in SECURITY_HEADERS["Permissions-Policy"]
    # No obsolete headers.
    assert "X-XSS-Protection" not in SECURITY_HEADERS


def test_normal_response_has_security_headers(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    for name, value in EXPECTED.items():
        assert response.headers[name] == value
    assert "Permissions-Policy" in response.headers


def test_api_error_response_has_security_headers(client: TestClient) -> None:
    # A 404 still passes through the middleware.
    response = client.get("/organizations/not-a-uuid")

    assert response.status_code >= 400
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


@pytest.mark.parametrize("name", list(EXPECTED))
def test_each_expected_header_present(client: TestClient, name: str) -> None:
    assert name in client.get("/health").headers
