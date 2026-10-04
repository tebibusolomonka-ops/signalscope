import dataclasses
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from signalscope.api.app import create_app
from signalscope.api.dependencies import database_session
from signalscope.api.lifespan import lifespan
from signalscope.core.settings import Settings

pytestmark = pytest.mark.anyio


async def client_for(settings: Settings) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    app = create_app(settings)
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield app, client


@pytest.fixture
async def ready_app(
    migrated_database: Settings, tmp_path: Path
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    settings = dataclasses.replace(migrated_database, blob_dir=tmp_path / "blobs")
    async for pair in client_for(settings):
        yield pair


async def test_ready_reports_all_dependencies(
    ready_app: tuple[FastAPI, httpx.AsyncClient],
) -> None:
    _, client = ready_app
    response = await client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    names = {component["name"] for component in body["components"]}
    assert {"database", "storage", "scheduler", "queue"} <= names
    assert "SIGNALSCOPE" not in response.text  # no settings or secrets leak


async def test_ready_is_unavailable_without_storage(migrated_database: Settings) -> None:
    settings = dataclasses.replace(migrated_database, blob_dir=None)
    async for _, client in client_for(settings):
        response = await client.get("/health/ready")

        assert response.status_code == 503
        storage = next(c for c in response.json()["components"] if c["name"] == "storage")
        assert storage["state"] == "unavailable"


async def test_ready_is_unavailable_when_the_database_fails(
    ready_app: tuple[FastAPI, httpx.AsyncClient],
) -> None:
    app, client = ready_app

    async def failing_session() -> AsyncIterator[object]:
        yield _FailingSession()

    app.dependency_overrides[database_session] = failing_session
    try:
        response = await client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(database_session, None)

    assert response.status_code == 503
    database = next(c for c in response.json()["components"] if c["name"] == "database")
    assert database["state"] == "unavailable"


class _FailingSession:
    async def execute(self, _statement: object) -> object:
        raise OperationalError("SELECT 1", {}, Exception("no connection"))

    async def scalar(self, _statement: object) -> int:
        raise OperationalError("SELECT count", {}, Exception("no connection"))
