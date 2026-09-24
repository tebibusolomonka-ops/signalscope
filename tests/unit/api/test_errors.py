from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.core.errors import ConflictError, NotFoundError


def test_not_found_error_returns_404(
    create_failing_app: Callable[[Exception], FastAPI],
) -> None:
    client = TestClient(create_failing_app(NotFoundError("Source was not found.")))

    response = client.get("/fail")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Source was not found."},
    }


def test_conflict_error_returns_409(create_failing_app: Callable[[Exception], FastAPI]) -> None:
    client = TestClient(create_failing_app(ConflictError()))

    response = client.get("/fail")

    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "conflict", "message": "Resource conflicts with existing data."},
    }


def test_unexpected_error_is_not_handled(
    create_failing_app: Callable[[Exception], FastAPI],
) -> None:
    client = TestClient(create_failing_app(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        client.get("/fail")


def test_unexpected_error_response_hides_details(
    create_failing_app: Callable[[Exception], FastAPI],
) -> None:
    app = create_failing_app(RuntimeError("secret detail"))
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/fail")

    assert response.status_code == 500
    assert "secret detail" not in response.text
    assert "Traceback" not in response.text
