import uuid
from collections.abc import Callable

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from signalscope.core.errors import NotFoundError


def is_uuid4(value: str) -> bool:
    try:
        return uuid.UUID(value).version == 4
    except ValueError:
        return False


def test_request_without_id_gets_new_uuid(client: TestClient) -> None:
    first = client.get("/health").headers["X-Request-ID"]
    second = client.get("/health").headers["X-Request-ID"]

    assert is_uuid4(first)
    assert is_uuid4(second)
    assert first != second


def test_valid_request_id_is_reused(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "client-id_1.2"})

    assert response.headers["X-Request-ID"] == "client-id_1.2"


@pytest.mark.parametrize("value", ["", "x" * 65, "has space", "semi;colon", "<script>"])
def test_unusable_request_id_is_replaced(client: TestClient, value: str) -> None:
    response = client.get("/health", headers={"X-Request-ID": value})

    assert is_uuid4(response.headers["X-Request-ID"])


def test_request_id_is_on_request_state(app: FastAPI, client: TestClient) -> None:
    @app.get("/request-id")
    async def read_request_id(request: Request) -> str:
        return str(request.state.request_id)

    response = client.get("/request-id")

    assert response.json() == response.headers["X-Request-ID"]


def test_error_response_has_request_id(
    create_failing_app: Callable[[Exception], FastAPI],
) -> None:
    client = TestClient(create_failing_app(NotFoundError()))

    response = client.get("/fail", headers={"X-Request-ID": "trace-me"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "trace-me"
