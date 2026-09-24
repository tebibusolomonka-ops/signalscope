from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.api.app import create_app
from signalscope.api.dependencies import DatabaseSession
from signalscope.core.errors import NotFoundError
from signalscope.core.settings import Settings

# The .invalid domain never resolves, so any connection attempt would fail.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def create_app_with_session_route(
    settings: Settings, sessions: list[AsyncSession], fail: bool = False
) -> FastAPI:
    app = create_app(settings)

    @app.get("/session")
    async def use_session(session: DatabaseSession) -> str:
        sessions.append(session)
        await session.begin()
        if fail:
            raise NotFoundError()
        return type(session).__name__

    return app


def test_yields_session_and_closes_it() -> None:
    sessions: list[AsyncSession] = []
    app = create_app_with_session_route(Settings(database_url=FAKE_DATABASE_URL), sessions)

    with TestClient(app) as client:
        response = client.get("/session")

        assert response.json() == "AsyncSession"
        [session] = sessions
        assert not session.in_transaction()


def test_closes_session_when_route_fails() -> None:
    sessions: list[AsyncSession] = []
    app = create_app_with_session_route(
        Settings(database_url=FAKE_DATABASE_URL), sessions, fail=True
    )

    with TestClient(app) as client:
        response = client.get("/session")

        assert response.status_code == 404
        [session] = sessions
        assert not session.in_transaction()


def test_returns_503_without_database() -> None:
    sessions: list[AsyncSession] = []
    app = create_app_with_session_route(Settings(), sessions)

    with TestClient(app) as client:
        response = client.get("/session")

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "service_unavailable", "message": "Database is not configured."},
    }
    assert sessions == []
