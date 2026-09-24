import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from signalscope.api.app import create_app
from signalscope.core.settings import LogLevel, Settings

# The .invalid domain never resolves, so any connection attempt would fail.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_running_app_has_settings_and_serves_requests() -> None:
    settings = Settings(app_name="SignalScope Test")
    app = create_app(settings)

    with TestClient(app) as client:
        assert app.state.settings is settings
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_startup_configures_logging_from_settings(capsys: pytest.CaptureFixture[str]) -> None:
    app = create_app(Settings(log_level=LogLevel.DEBUG))

    with TestClient(app):
        logging.getLogger("signalscope.test").debug("debug message")

    assert "DEBUG    signalscope.test: debug message" in capsys.readouterr().err


def test_logs_start_and_stop(caplog: pytest.LogCaptureFixture) -> None:
    app = create_app(Settings(app_name="SignalScope Test"))

    with TestClient(app):
        pass

    assert "SignalScope Test started in development" in caplog.messages
    assert "SignalScope Test stopped" in caplog.messages


def test_starts_without_database() -> None:
    app = create_app(Settings())

    with TestClient(app) as client:
        assert app.state.session_factory is None
        assert client.get("/health").status_code == 200


def test_creates_session_factory_when_database_is_configured() -> None:
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app) as client:
        assert isinstance(app.state.session_factory, async_sessionmaker)
        assert client.get("/health").status_code == 200


def test_disposes_engine_on_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    disposed: list[AsyncEngine] = []
    original_dispose = AsyncEngine.dispose

    async def record_dispose(self: AsyncEngine, close: bool = True) -> None:
        disposed.append(self)
        await original_dispose(self, close)

    monkeypatch.setattr(AsyncEngine, "dispose", record_dispose)
    app = create_app(Settings(database_url=FAKE_DATABASE_URL))

    with TestClient(app):
        assert disposed == []

    [engine] = disposed
    assert engine.url.host == "db.invalid"
