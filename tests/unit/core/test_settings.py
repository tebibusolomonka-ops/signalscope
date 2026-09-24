import dataclasses

import pytest

from signalscope.core.settings import Environment, LogLevel, Settings, SettingsError


def test_defaults() -> None:
    settings = Settings()

    assert settings.app_name == "SignalScope"
    assert settings.environment is Environment.DEVELOPMENT
    assert settings.debug is False
    assert settings.log_level is LogLevel.INFO


def test_custom_values() -> None:
    settings = Settings(
        app_name="SignalScope Test",
        environment=Environment.PRODUCTION,
        debug=True,
        log_level=LogLevel.WARNING,
    )

    assert settings.app_name == "SignalScope Test"
    assert settings.environment is Environment.PRODUCTION
    assert settings.debug is True
    assert settings.log_level is LogLevel.WARNING


def test_settings_cannot_be_changed() -> None:
    settings = Settings()

    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.debug = True  # type: ignore[misc]


@pytest.mark.parametrize("app_name", ["", "   "])
def test_empty_app_name_is_rejected(app_name: str) -> None:
    with pytest.raises(SettingsError, match="app_name"):
        Settings(app_name=app_name)
