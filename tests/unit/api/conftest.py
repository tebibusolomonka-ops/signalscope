from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import Settings


@pytest.fixture
def app() -> FastAPI:
    return create_app(Settings())


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def create_failing_app() -> Callable[[Exception], FastAPI]:
    """Return a function that builds an app where GET /fail raises the given error."""

    def create(error: Exception) -> FastAPI:
        app = create_app(Settings())

        @app.get("/fail")
        async def fail() -> None:
            raise error

        return app

    return create
