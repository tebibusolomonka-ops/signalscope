import dataclasses
from pathlib import Path

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
    assert settings.blob_dir is None


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
    assert Settings().organization_export_retention_days == 30


def test_load_settings_reads_organization_export_retention() -> None:
    settings = load_settings({"SIGNALSCOPE_ORGANIZATION_EXPORT_RETENTION_DAYS": "45"})

    assert settings.organization_export_retention_days == 45


def test_load_settings_reads_organization_export_limits() -> None:
    settings = load_settings(
        {
            "SIGNALSCOPE_ORGANIZATION_EXPORT_MAX_ASSETS": "25",
            "SIGNALSCOPE_ORGANIZATION_EXPORT_MAX_BYTES": "4096",
        }
    )

    assert settings.organization_export_max_assets == 25
    assert settings.organization_export_max_bytes == 4096


@pytest.mark.parametrize("days", [0, 366])
def test_organization_export_retention_is_bounded(days: int) -> None:
    with pytest.raises(SettingsError, match="organization_export_retention_days"):
        Settings(organization_export_retention_days=days)


def test_load_settings_reads_all_values() -> None:
    settings = load_settings(
        {
            "SIGNALSCOPE_APP_NAME": "SignalScope Staging",
            "SIGNALSCOPE_ENVIRONMENT": "production",
            "SIGNALSCOPE_DEBUG": "true",
            "SIGNALSCOPE_LOG_LEVEL": "DEBUG",
            "SIGNALSCOPE_DATABASE_URL": DATABASE_URL,
            "SIGNALSCOPE_BLOB_DIR": " /var/lib/signalscope/blobs ",
        }
    )

    assert settings == Settings(
        app_name="SignalScope Staging",
        environment=Environment.PRODUCTION,
        debug=True,
        log_level=LogLevel.DEBUG,
        database_url=DATABASE_URL,
        blob_dir=Path("/var/lib/signalscope/blobs"),
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
            "SIGNALSCOPE_BLOB_DIR": "  ",
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


def test_local_embeddings_are_off_by_default() -> None:
    settings = load_settings({})

    assert settings.local_embeddings_enabled is False
    assert settings.local_embedding_device == "cpu"
    assert settings.local_embedding_batch_size == 32
    assert settings.local_embedding_cache_dir is None


def test_load_local_embedding_settings() -> None:
    settings = load_settings(
        {
            "SIGNALSCOPE_LOCAL_EMBEDDINGS_ENABLED": "true",
            "SIGNALSCOPE_LOCAL_EMBEDDING_DEVICE": "cuda",
            "SIGNALSCOPE_LOCAL_EMBEDDING_BATCH_SIZE": " 8 ",
            "SIGNALSCOPE_LOCAL_EMBEDDING_CACHE_DIR": "/var/cache/models",
        }
    )

    assert settings.local_embeddings_enabled is True
    assert settings.local_embedding_device == "cuda"
    assert settings.local_embedding_batch_size == 8
    assert settings.local_embedding_cache_dir == Path("/var/cache/models")


@pytest.mark.parametrize("value", ["0", "-4"])
def test_batch_size_must_be_positive(value: str) -> None:
    with pytest.raises(SettingsError, match="local_embedding_batch_size"):
        load_settings({"SIGNALSCOPE_LOCAL_EMBEDDING_BATCH_SIZE": value})


def test_batch_size_must_be_a_number() -> None:
    with pytest.raises(SettingsError, match="SIGNALSCOPE_LOCAL_EMBEDDING_BATCH_SIZE"):
        load_settings({"SIGNALSCOPE_LOCAL_EMBEDDING_BATCH_SIZE": "many"})


def test_device_must_not_be_blank() -> None:
    with pytest.raises(SettingsError, match="local_embedding_device"):
        Settings(local_embedding_device="  ")


def test_enabled_must_be_true_or_false() -> None:
    with pytest.raises(SettingsError, match="SIGNALSCOPE_LOCAL_EMBEDDINGS_ENABLED"):
        load_settings({"SIGNALSCOPE_LOCAL_EMBEDDINGS_ENABLED": "maybe"})


def test_local_reranking_is_off_by_default() -> None:
    settings = load_settings({})

    assert settings.local_reranking_enabled is False
    assert settings.local_reranking_device == "cpu"
    assert settings.local_reranking_batch_size == 16


def test_load_local_reranking_settings() -> None:
    settings = load_settings(
        {
            "SIGNALSCOPE_LOCAL_RERANKING_ENABLED": "yes",
            "SIGNALSCOPE_LOCAL_RERANKING_DEVICE": "cuda:1",
            "SIGNALSCOPE_LOCAL_RERANKING_BATCH_SIZE": "4",
        }
    )

    assert settings.local_reranking_enabled is True
    assert settings.local_reranking_device == "cuda:1"
    assert settings.local_reranking_batch_size == 4


@pytest.mark.parametrize("value", ["0", "-1"])
def test_reranking_batch_size_must_be_positive(value: str) -> None:
    with pytest.raises(SettingsError, match="local_reranking_batch_size"):
        load_settings({"SIGNALSCOPE_LOCAL_RERANKING_BATCH_SIZE": value})


def test_reranking_batch_size_must_be_a_number() -> None:
    with pytest.raises(SettingsError, match="SIGNALSCOPE_LOCAL_RERANKING_BATCH_SIZE"):
        load_settings({"SIGNALSCOPE_LOCAL_RERANKING_BATCH_SIZE": "lots"})


def test_reranking_device_must_not_be_blank() -> None:
    with pytest.raises(SettingsError, match="local_reranking_device"):
        Settings(local_reranking_device=" ")


def test_local_entities_are_off_by_default() -> None:
    settings = load_settings({})

    assert settings.local_entities_enabled is False
    assert (settings.local_entity_device, settings.local_entity_threshold) == ("cpu", 0.5)


def test_load_local_entity_settings() -> None:
    settings = load_settings(
        {
            "SIGNALSCOPE_LOCAL_ENTITIES_ENABLED": "on",
            "SIGNALSCOPE_LOCAL_ENTITY_DEVICE": "cuda",
            "SIGNALSCOPE_LOCAL_ENTITY_THRESHOLD": " 0.35 ",
        }
    )

    assert settings.local_entities_enabled is True
    assert (settings.local_entity_device, settings.local_entity_threshold) == ("cuda", 0.35)


@pytest.mark.parametrize("value", ["0", "-0.2", "1.01"])
def test_entity_threshold_bounds(value: str) -> None:
    with pytest.raises(SettingsError, match="local_entity_threshold"):
        load_settings({"SIGNALSCOPE_LOCAL_ENTITY_THRESHOLD": value})


@pytest.mark.parametrize("value", ["high", "nan", "inf"])
def test_entity_threshold_must_be_a_finite_number(value: str) -> None:
    with pytest.raises(SettingsError, match="SIGNALSCOPE_LOCAL_ENTITY_THRESHOLD"):
        load_settings({"SIGNALSCOPE_LOCAL_ENTITY_THRESHOLD": value})


def test_entity_threshold_of_one_is_allowed() -> None:
    assert load_settings({"SIGNALSCOPE_LOCAL_ENTITY_THRESHOLD": "1"}).local_entity_threshold == 1.0


def test_local_structured_extraction_is_off_by_default() -> None:
    settings = load_settings({})

    assert (settings.local_structured_enabled, settings.local_structured_device) == (False, "cpu")


def test_load_local_structured_settings() -> None:
    settings = load_settings(
        {
            "SIGNALSCOPE_LOCAL_STRUCTURED_ENABLED": "yes",
            "SIGNALSCOPE_LOCAL_STRUCTURED_DEVICE": " cuda ",
        }
    )

    assert (settings.local_structured_enabled, settings.local_structured_device) == (True, "cuda")


def test_structured_device_must_not_be_blank() -> None:
    with pytest.raises(SettingsError, match="local_structured_device"):
        Settings(local_structured_device=" ")


def test_local_answers_are_off_by_default() -> None:
    settings = load_settings({})

    assert (
        settings.local_answers_enabled,
        settings.local_answer_device,
        settings.local_answer_max_new_tokens,
    ) == (False, "cpu", 512)


def test_load_local_answer_settings() -> None:
    settings = load_settings(
        {
            "SIGNALSCOPE_LOCAL_ANSWERS_ENABLED": "true",
            "SIGNALSCOPE_LOCAL_ANSWER_DEVICE": "cuda",
            "SIGNALSCOPE_LOCAL_ANSWER_MAX_NEW_TOKENS": "256",
        }
    )

    assert (
        settings.local_answers_enabled,
        settings.local_answer_device,
        settings.local_answer_max_new_tokens,
    ) == (True, "cuda", 256)


@pytest.mark.parametrize("value", ["0", "-5", "4097"])
def test_answer_token_bounds(value: str) -> None:
    with pytest.raises(SettingsError, match="local_answer_max_new_tokens"):
        load_settings({"SIGNALSCOPE_LOCAL_ANSWER_MAX_NEW_TOKENS": value})


def test_answer_tokens_must_be_a_number() -> None:
    with pytest.raises(SettingsError, match="SIGNALSCOPE_LOCAL_ANSWER_MAX_NEW_TOKENS"):
        load_settings({"SIGNALSCOPE_LOCAL_ANSWER_MAX_NEW_TOKENS": "many"})


def test_answer_device_must_not_be_blank() -> None:
    with pytest.raises(SettingsError, match="local_answer_device"):
        Settings(local_answer_device=" ")


def test_session_lifetime_defaults() -> None:
    settings = Settings()
    assert settings.auth_session_max_age_seconds == 604_800
    assert settings.auth_session_idle_seconds == 86_400


def test_load_settings_reads_session_lifetimes() -> None:
    settings = load_settings(
        {
            "SIGNALSCOPE_AUTH_SESSION_MAX_AGE_SECONDS": "7200",
            "SIGNALSCOPE_AUTH_SESSION_IDLE_SECONDS": "1800",
        }
    )
    assert settings.auth_session_max_age_seconds == 7200
    assert settings.auth_session_idle_seconds == 1800


@pytest.mark.parametrize("seconds", [0, 59, 31_536_001])
def test_session_max_age_is_bounded(seconds: int) -> None:
    with pytest.raises(SettingsError, match="auth_session_max_age_seconds"):
        Settings(auth_session_max_age_seconds=seconds)


@pytest.mark.parametrize("seconds", [0, 31_536_001])
def test_session_idle_is_bounded(seconds: int) -> None:
    with pytest.raises(SettingsError, match="auth_session_idle_seconds"):
        Settings(auth_session_idle_seconds=seconds)


def test_idle_must_not_exceed_absolute_lifetime() -> None:
    with pytest.raises(SettingsError, match="must not exceed"):
        Settings(auth_session_max_age_seconds=600, auth_session_idle_seconds=1200)


def test_json_request_limit_default_and_env() -> None:
    assert Settings().max_json_request_bytes == 1_000_000
    loaded = load_settings({"SIGNALSCOPE_MAX_JSON_REQUEST_BYTES": "2048"})
    assert loaded.max_json_request_bytes == 2048


@pytest.mark.parametrize("value", [0, 1023, 100_000_001])
def test_json_request_limit_is_bounded(value: int) -> None:
    with pytest.raises(SettingsError, match="max_json_request_bytes"):
        Settings(max_json_request_bytes=value)


def test_upload_request_limit_default_and_env() -> None:
    assert Settings().max_upload_request_bytes == 512_000_000
    loaded = load_settings({"SIGNALSCOPE_MAX_UPLOAD_REQUEST_BYTES": "4096"})
    assert loaded.max_upload_request_bytes == 4096


@pytest.mark.parametrize("value", [0, 1023, 2_000_000_001])
def test_upload_request_limit_is_bounded(value: int) -> None:
    with pytest.raises(SettingsError, match="max_upload_request_bytes"):
        Settings(max_upload_request_bytes=value)
