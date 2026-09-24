import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.core.settings import Settings


def create_app_that_raises(error: Exception) -> FastAPI:
    app = create_app(Settings())

    @app.get("/fail")
    async def fail() -> None:
        raise error

    return app


def test_not_found_error_returns_404() -> None:
    client = TestClient(create_app_that_raises(NotFoundError("Source was not found.")))

    response = client.get("/fail")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Source was not found."},
    }


def test_conflict_error_returns_409() -> None:
    client = TestClient(create_app_that_raises(ConflictError()))

    response = client.get("/fail")

    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "conflict", "message": "Resource conflicts with existing data."},
    }


def test_unexpected_error_is_not_handled() -> None:
    client = TestClient(create_app_that_raises(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        client.get("/fail")


def test_unexpected_error_response_hides_details() -> None:
    app = create_app_that_raises(RuntimeError("secret detail"))
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/fail")

    assert response.status_code == 500
    assert "secret detail" not in response.text
    assert "Traceback" not in response.text
