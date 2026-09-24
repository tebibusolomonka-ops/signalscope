import pytest
from fastapi import FastAPI

from signalscope.api.app import create_app
from signalscope.core.settings import Settings


def test_create_app_uses_given_settings() -> None:
    app = create_app(Settings(app_name="SignalScope Test", debug=True))

    assert isinstance(app, FastAPI)
    assert app.title == "SignalScope Test"
    assert app.debug is True


def test_create_app_loads_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNALSCOPE_APP_NAME", "SignalScope From Env")

    app = create_app()

    assert app.title == "SignalScope From Env"
