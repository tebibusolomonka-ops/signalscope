import dataclasses

import pytest

from signalscope.core.settings import (
    Environment,
    LogLevel,
    Settings,
    SettingsError,
    load_settings,
)

DATABASE_URL = "postgresql+asyncpg://signalscope:signalscope@localhost:5432/signalscope"


def test_defaults() -> None:
    settings = Settings()

    assert settings.app_name == "SignalScope"
    assert settings.environment is Environment.DEVELOPMENT
    assert settings.debug is False
    assert settings.log_level is LogLevel.INFO
    assert settings.database_url is None


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


def test_load_settings_uses_defaults_when_nothing_is_set() -> None:
    assert load_settings({}) == Settings()


def test_load_settings_reads_all_values() -> None:
    settings = load_settings(
        {
            "SIGNALSCOPE_APP_NAME": "SignalScope Staging",
            "SIGNALSCOPE_ENVIRONMENT": "production",
            "SIGNALSCOPE_DEBUG": "true",
            "SIGNALSCOPE_LOG_LEVEL": "DEBUG",
            "SIGNALSCOPE_DATABASE_URL": DATABASE_URL,
        }
    )

    assert settings == Settings(
        app_name="SignalScope Staging",
        environment=Environment.PRODUCTION,
        debug=True,
        log_level=LogLevel.DEBUG,
        database_url=DATABASE_URL,
    )


def test_load_settings_reads_os_environ_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNALSCOPE_LOG_LEVEL", "ERROR")

    assert load_settings().log_level is LogLevel.ERROR


def test_load_settings_ignores_empty_values() -> None:
    settings = load_settings(
        {
            "SIGNALSCOPE_APP_NAME": "  ",
            "SIGNALSCOPE_ENVIRONMENT": "",
            "SIGNALSCOPE_DEBUG": "",
            "SIGNALSCOPE_LOG_LEVEL": "",
            "SIGNALSCOPE_DATABASE_URL": "",
        }
    )

    assert settings == Settings()


def test_load_settings_strips_whitespace() -> None:
    settings = load_settings({"SIGNALSCOPE_APP_NAME": "  SignalScope Dev  "})

    assert settings.app_name == "SignalScope Dev"


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "Yes", "on", " true "])
def test_debug_true_values(value: str) -> None:
    assert load_settings({"SIGNALSCOPE_DEBUG": value}).debug is True


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "No", "off", " false "])
def test_debug_false_values(value: str) -> None:
    assert load_settings({"SIGNALSCOPE_DEBUG": value}).debug is False


@pytest.mark.parametrize("value", ["maybe", "2", "enabled", "t"])
def test_invalid_debug_value_is_rejected(value: str) -> None:
    with pytest.raises(SettingsError, match="SIGNALSCOPE_DEBUG must be true or false"):
        load_settings({"SIGNALSCOPE_DEBUG": value})


def test_environment_is_case_insensitive() -> None:
    settings = load_settings({"SIGNALSCOPE_ENVIRONMENT": "Production"})

    assert settings.environment is Environment.PRODUCTION


def test_log_level_is_case_insensitive() -> None:
    settings = load_settings({"SIGNALSCOPE_LOG_LEVEL": "warning"})

    assert settings.log_level is LogLevel.WARNING


def test_invalid_environment_is_rejected() -> None:
    with pytest.raises(SettingsError, match="SIGNALSCOPE_ENVIRONMENT must be one of"):
        load_settings({"SIGNALSCOPE_ENVIRONMENT": "staging"})


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(SettingsError, match="SIGNALSCOPE_LOG_LEVEL must be one of"):
        load_settings({"SIGNALSCOPE_LOG_LEVEL": "VERBOSE"})


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///signalscope.db",
        "postgresql://signalscope:fake-password@localhost:5432/signalscope",
        "postgresql+psycopg://signalscope:fake-password@localhost:5432/signalscope",
        "mysql://signalscope:fake-password@localhost:3306/signalscope",
    ],
)
def test_database_url_must_use_asyncpg(url: str) -> None:
    with pytest.raises(SettingsError, match="Database URL must start with") as error:
        load_settings({"SIGNALSCOPE_DATABASE_URL": url})

    assert "fake-password" not in str(error.value)


def test_database_url_is_not_shown_in_repr() -> None:
    settings = Settings(database_url=DATABASE_URL)

    assert DATABASE_URL not in repr(settings)
