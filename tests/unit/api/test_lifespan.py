import logging

import pytest
from fastapi.testclient import TestClient

from signalscope.api.app import create_app
from signalscope.core.settings import LogLevel, Settings


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
