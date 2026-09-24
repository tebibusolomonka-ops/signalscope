import uuid

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.errors import NotFoundError
from signalscope.core.settings import Settings


def is_uuid4(value: str) -> bool:
    try:
        return uuid.UUID(value).version == 4
    except ValueError:
        return False


def test_request_without_id_gets_new_uuid() -> None:
    client = TestClient(create_app(Settings()))

    first = client.get("/health").headers["X-Request-ID"]
    second = client.get("/health").headers["X-Request-ID"]

    assert is_uuid4(first)
    assert is_uuid4(second)
    assert first != second


def test_valid_request_id_is_reused() -> None:
    client = TestClient(create_app(Settings()))

    response = client.get("/health", headers={"X-Request-ID": "client-id_1.2"})

    assert response.headers["X-Request-ID"] == "client-id_1.2"


@pytest.mark.parametrize("value", ["", "x" * 65, "has space", "semi;colon", "<script>"])
def test_unusable_request_id_is_replaced(value: str) -> None:
    client = TestClient(create_app(Settings()))

    response = client.get("/health", headers={"X-Request-ID": value})

    assert is_uuid4(response.headers["X-Request-ID"])


def test_request_id_is_on_request_state() -> None:
    app = create_app(Settings())

    @app.get("/request-id")
    async def read_request_id(request: Request) -> str:
        return str(request.state.request_id)

    response = TestClient(app).get("/request-id")

    assert response.json() == response.headers["X-Request-ID"]


def test_error_response_has_request_id() -> None:
    app = create_app(Settings())

    @app.get("/missing")
    async def missing() -> None:
        raise NotFoundError()

    response = TestClient(app).get("/missing", headers={"X-Request-ID": "trace-me"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "trace-me"
