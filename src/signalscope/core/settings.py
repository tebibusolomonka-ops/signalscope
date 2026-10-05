import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from signalscope.core.errors import SignalScopeError

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})
DATABASE_URL_PREFIX = "postgresql+asyncpg://"
# A cap on answer length, so a typo cannot ask for a very long, slow generation.
MAX_ANSWER_TOKENS = 4096
MAX_AUTH_SESSION_DAYS = 365
MAX_AUTH_SESSION_RETENTION_DAYS = 3650
# Absolute and idle session lifetimes, in seconds. One year is the ceiling.
MIN_AUTH_SESSION_SECONDS = 60
MAX_AUTH_SESSION_SECONDS = 31_536_000
# Bounds for the maximum accepted JSON request body, in bytes.
MIN_JSON_REQUEST_BYTES = 1_024
MAX_JSON_REQUEST_BYTES = 100_000_000
MAX_AUTH_LOGIN_WINDOW_SECONDS = 86_400
MAX_AUTH_LOGIN_FAILURES = 100
MAX_AUTH_LOGIN_BLOCK_SECONDS = 604_800
MAX_ORGANIZATION_INVITATION_DAYS = 90
MAX_INVITATION_RETENTION_DAYS = 365
MAX_ORGANIZATION_EXPORT_RETENTION_DAYS = 365
MAX_ORGANIZATION_EXPORT_ASSETS = 1_000_000
MAX_ORGANIZATION_EXPORT_BYTES = 10_000_000_000


class SettingsError(SignalScopeError, ValueError):
    pass


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True, kw_only=True)
class Settings:
    app_name: str = "SignalScope"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    log_level: LogLevel = LogLevel.INFO
    # Left out of repr because the URL can contain a password.
    database_url: str | None = field(default=None, repr=False)
    # Folder for raw file bytes, such as imported PDFs.
    blob_dir: Path | None = None
    # The local multilingual E5 model. Off by default, because it needs the
    # local-embeddings extra and downloads the model on first use.
    local_embeddings_enabled: bool = False
    # Where the model runs, such as "cpu" or "cuda".
    local_embedding_device: str = "cpu"
    # How many texts the model embeds in one pass.
    local_embedding_batch_size: int = 32
    # Where downloaded model files are kept. Unset means the library default.
    local_embedding_cache_dir: Path | None = None
    # The local mMARCO reranker. Off by default, for the same reasons.
    local_reranking_enabled: bool = False
    local_reranking_device: str = "cpu"
    # How many query and passage pairs the reranker scores in one pass.
    local_reranking_batch_size: int = 16
    # The local GLiNER entity model. Off by default, for the same reasons.
    local_entities_enabled: bool = False
    local_entity_device: str = "cpu"
    # Spans the model scores lower than this are left out.
    local_entity_threshold: float = 0.5
    # The local GLiNER2 model that reads events and claims. Off by default, for
    # the same reasons.
    local_structured_enabled: bool = False
    local_structured_device: str = "cpu"
    # The local Qwen answer model. Off by default, for the same reasons.
    local_answers_enabled: bool = False
    local_answer_device: str = "cpu"
    # The longest answer the model may write, in tokens.
    local_answer_max_new_tokens: int = 512
    # Sign in and access rules for investigations and organizations. Off by
    # default, so existing APIs keep working without a login.
    auth_enabled: bool = False
    # How long a login session lasts before it expires.
    auth_session_days: int = 7
    # Absolute session lifetime: a session older than this is invalid even if
    # used, measured from when it was created. Default 7 days.
    auth_session_max_age_seconds: int = 604_800
    # Idle session lifetime: a session not used within this time is invalid.
    # Default 1 day. Must not exceed the absolute lifetime.
    auth_session_idle_seconds: int = 86_400
    # How long expired and revoked sessions are kept before cleanup-auth-sessions
    # deletes them.
    auth_session_retention_days: int = 30
    # The largest JSON request body the API accepts. Larger ones answer 413.
    # Binary uploads such as archives have their own, larger limits.
    max_json_request_bytes: int = 1_000_000
    auth_login_window_seconds: int = 900
    auth_login_max_failures: int = 10
    auth_login_block_seconds: int = 900
    # How long an organization invitation can be accepted.
    organization_invitation_days: int = 7
    # How long used, revoked and expired invitations are kept before
    # cleanup-organization-invitations deletes them.
    organization_invitation_retention_days: int = 30
    # How long completed and failed portable exports remain available.
    organization_export_retention_days: int = 30
    organization_export_max_assets: int = 10_000
    organization_export_max_bytes: int = 500_000_000

    def __post_init__(self) -> None:
        if not self.app_name.strip():
            raise SettingsError("app_name must not be empty")
        if not self.local_embedding_device.strip():
            raise SettingsError("local_embedding_device must not be empty")
        if self.local_embedding_batch_size < 1:
            raise SettingsError("local_embedding_batch_size must be at least 1")
        if not self.local_reranking_device.strip():
            raise SettingsError("local_reranking_device must not be empty")
        if self.local_reranking_batch_size < 1:
            raise SettingsError("local_reranking_batch_size must be at least 1")
        if not self.local_entity_device.strip():
            raise SettingsError("local_entity_device must not be empty")
        if not 0 < self.local_entity_threshold <= 1:
            raise SettingsError("local_entity_threshold must be above 0 and at most 1")
        if not self.local_structured_device.strip():
            raise SettingsError("local_structured_device must not be empty")
        if not self.local_answer_device.strip():
            raise SettingsError("local_answer_device must not be empty")
        if not 1 <= self.local_answer_max_new_tokens <= MAX_ANSWER_TOKENS:
            raise SettingsError(
                f"local_answer_max_new_tokens must be from 1 to {MAX_ANSWER_TOKENS}"
            )
        if not 1 <= self.auth_session_days <= MAX_AUTH_SESSION_DAYS:
            raise SettingsError(f"auth_session_days must be from 1 to {MAX_AUTH_SESSION_DAYS}")
        if not (
            MIN_AUTH_SESSION_SECONDS
            <= self.auth_session_max_age_seconds
            <= MAX_AUTH_SESSION_SECONDS
        ):
            raise SettingsError(
                "auth_session_max_age_seconds must be from "
                f"{MIN_AUTH_SESSION_SECONDS} to {MAX_AUTH_SESSION_SECONDS}"
            )
        if not (
            MIN_AUTH_SESSION_SECONDS <= self.auth_session_idle_seconds <= MAX_AUTH_SESSION_SECONDS
        ):
            raise SettingsError(
                "auth_session_idle_seconds must be from "
                f"{MIN_AUTH_SESSION_SECONDS} to {MAX_AUTH_SESSION_SECONDS}"
            )
        if self.auth_session_idle_seconds > self.auth_session_max_age_seconds:
            raise SettingsError(
                "auth_session_idle_seconds must not exceed auth_session_max_age_seconds"
            )
        if not MIN_JSON_REQUEST_BYTES <= self.max_json_request_bytes <= MAX_JSON_REQUEST_BYTES:
            raise SettingsError(
                "max_json_request_bytes must be from "
                f"{MIN_JSON_REQUEST_BYTES} to {MAX_JSON_REQUEST_BYTES}"
            )
        if not 1 <= self.auth_session_retention_days <= MAX_AUTH_SESSION_RETENTION_DAYS:
            raise SettingsError(
                f"auth_session_retention_days must be from 1 to {MAX_AUTH_SESSION_RETENTION_DAYS}"
            )
        if not 1 <= self.auth_login_window_seconds <= MAX_AUTH_LOGIN_WINDOW_SECONDS:
            raise SettingsError(
                f"auth_login_window_seconds must be from 1 to {MAX_AUTH_LOGIN_WINDOW_SECONDS}"
            )
        if not 1 <= self.auth_login_max_failures <= MAX_AUTH_LOGIN_FAILURES:
            raise SettingsError(
                f"auth_login_max_failures must be from 1 to {MAX_AUTH_LOGIN_FAILURES}"
            )
        if not 1 <= self.auth_login_block_seconds <= MAX_AUTH_LOGIN_BLOCK_SECONDS:
            raise SettingsError(
                f"auth_login_block_seconds must be from 1 to {MAX_AUTH_LOGIN_BLOCK_SECONDS}"
            )
        if not 1 <= self.organization_invitation_days <= MAX_ORGANIZATION_INVITATION_DAYS:
            raise SettingsError(
                f"organization_invitation_days must be from 1 to {MAX_ORGANIZATION_INVITATION_DAYS}"
            )
        if not 1 <= self.organization_invitation_retention_days <= MAX_INVITATION_RETENTION_DAYS:
            raise SettingsError(
                "organization_invitation_retention_days must be from 1 to "
                f"{MAX_INVITATION_RETENTION_DAYS}"
            )
        if (
            not 1
            <= self.organization_export_retention_days
            <= MAX_ORGANIZATION_EXPORT_RETENTION_DAYS
        ):
            raise SettingsError(
                "organization_export_retention_days must be from 1 to "
                f"{MAX_ORGANIZATION_EXPORT_RETENTION_DAYS}"
            )
        if not 1 <= self.organization_export_max_assets <= MAX_ORGANIZATION_EXPORT_ASSETS:
            raise SettingsError(
                f"organization_export_max_assets must be from 1 to {MAX_ORGANIZATION_EXPORT_ASSETS}"
            )
        if not 1 <= self.organization_export_max_bytes <= MAX_ORGANIZATION_EXPORT_BYTES:
            raise SettingsError(
                f"organization_export_max_bytes must be from 1 to {MAX_ORGANIZATION_EXPORT_BYTES}"
            )
        if self.database_url is not None and not self.database_url.startswith(DATABASE_URL_PREFIX):
            raise SettingsError(f"Database URL must start with {DATABASE_URL_PREFIX}")


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Build settings from SIGNALSCOPE_* environment variables.

    Reads os.environ unless another mapping is given. Variables that are
    missing or empty keep their default value.
    """
    env = os.environ if environ is None else environ
    defaults = Settings()
    return Settings(
        app_name=_read_str(env, "SIGNALSCOPE_APP_NAME", defaults.app_name),
        environment=_read_enum(env, "SIGNALSCOPE_ENVIRONMENT", Environment, defaults.environment),
        debug=_read_bool(env, "SIGNALSCOPE_DEBUG", defaults.debug),
        log_level=_read_enum(env, "SIGNALSCOPE_LOG_LEVEL", LogLevel, defaults.log_level),
        database_url=_read(env, "SIGNALSCOPE_DATABASE_URL"),
        blob_dir=_read_path(env, "SIGNALSCOPE_BLOB_DIR"),
        local_embeddings_enabled=_read_bool(
            env, "SIGNALSCOPE_LOCAL_EMBEDDINGS_ENABLED", defaults.local_embeddings_enabled
        ),
        local_embedding_device=_read_str(
            env, "SIGNALSCOPE_LOCAL_EMBEDDING_DEVICE", defaults.local_embedding_device
        ),
        local_embedding_batch_size=_read_int(
            env, "SIGNALSCOPE_LOCAL_EMBEDDING_BATCH_SIZE", defaults.local_embedding_batch_size
        ),
        local_embedding_cache_dir=_read_path(env, "SIGNALSCOPE_LOCAL_EMBEDDING_CACHE_DIR"),
        local_reranking_enabled=_read_bool(
            env, "SIGNALSCOPE_LOCAL_RERANKING_ENABLED", defaults.local_reranking_enabled
        ),
        local_reranking_device=_read_str(
            env, "SIGNALSCOPE_LOCAL_RERANKING_DEVICE", defaults.local_reranking_device
        ),
        local_reranking_batch_size=_read_int(
            env, "SIGNALSCOPE_LOCAL_RERANKING_BATCH_SIZE", defaults.local_reranking_batch_size
        ),
        local_entities_enabled=_read_bool(
            env, "SIGNALSCOPE_LOCAL_ENTITIES_ENABLED", defaults.local_entities_enabled
        ),
        local_entity_device=_read_str(
            env, "SIGNALSCOPE_LOCAL_ENTITY_DEVICE", defaults.local_entity_device
        ),
        local_entity_threshold=_read_float(
            env, "SIGNALSCOPE_LOCAL_ENTITY_THRESHOLD", defaults.local_entity_threshold
        ),
        local_structured_enabled=_read_bool(
            env, "SIGNALSCOPE_LOCAL_STRUCTURED_ENABLED", defaults.local_structured_enabled
        ),
        local_structured_device=_read_str(
            env, "SIGNALSCOPE_LOCAL_STRUCTURED_DEVICE", defaults.local_structured_device
        ),
        local_answers_enabled=_read_bool(
            env, "SIGNALSCOPE_LOCAL_ANSWERS_ENABLED", defaults.local_answers_enabled
        ),
        local_answer_device=_read_str(
            env, "SIGNALSCOPE_LOCAL_ANSWER_DEVICE", defaults.local_answer_device
        ),
        local_answer_max_new_tokens=_read_int(
            env,
            "SIGNALSCOPE_LOCAL_ANSWER_MAX_NEW_TOKENS",
            defaults.local_answer_max_new_tokens,
        ),
        auth_enabled=_read_bool(env, "SIGNALSCOPE_AUTH_ENABLED", defaults.auth_enabled),
        auth_session_days=_read_int(
            env, "SIGNALSCOPE_AUTH_SESSION_DAYS", defaults.auth_session_days
        ),
        max_json_request_bytes=_read_int(
            env, "SIGNALSCOPE_MAX_JSON_REQUEST_BYTES", defaults.max_json_request_bytes
        ),
        auth_session_max_age_seconds=_read_int(
            env,
            "SIGNALSCOPE_AUTH_SESSION_MAX_AGE_SECONDS",
            defaults.auth_session_max_age_seconds,
        ),
        auth_session_idle_seconds=_read_int(
            env, "SIGNALSCOPE_AUTH_SESSION_IDLE_SECONDS", defaults.auth_session_idle_seconds
        ),
        auth_session_retention_days=_read_int(
            env,
            "SIGNALSCOPE_AUTH_SESSION_RETENTION_DAYS",
            defaults.auth_session_retention_days,
        ),
        auth_login_window_seconds=_read_int(
            env, "SIGNALSCOPE_AUTH_LOGIN_WINDOW_SECONDS", defaults.auth_login_window_seconds
        ),
        auth_login_max_failures=_read_int(
            env, "SIGNALSCOPE_AUTH_LOGIN_MAX_FAILURES", defaults.auth_login_max_failures
        ),
        auth_login_block_seconds=_read_int(
            env, "SIGNALSCOPE_AUTH_LOGIN_BLOCK_SECONDS", defaults.auth_login_block_seconds
        ),
        organization_invitation_days=_read_int(
            env,
            "SIGNALSCOPE_ORGANIZATION_INVITATION_DAYS",
            defaults.organization_invitation_days,
        ),
        organization_invitation_retention_days=_read_int(
            env,
            "SIGNALSCOPE_ORGANIZATION_INVITATION_RETENTION_DAYS",
            defaults.organization_invitation_retention_days,
        ),
        organization_export_retention_days=_read_int(
            env,
            "SIGNALSCOPE_ORGANIZATION_EXPORT_RETENTION_DAYS",
            defaults.organization_export_retention_days,
        ),
        organization_export_max_assets=_read_int(
            env,
            "SIGNALSCOPE_ORGANIZATION_EXPORT_MAX_ASSETS",
            defaults.organization_export_max_assets,
        ),
        organization_export_max_bytes=_read_int(
            env,
            "SIGNALSCOPE_ORGANIZATION_EXPORT_MAX_BYTES",
            defaults.organization_export_max_bytes,
        ),
    )


def _read(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name, "").strip()
    return value or None


def _read_path(env: Mapping[str, str], name: str) -> Path | None:
    value = _read(env, name)
    return None if value is None else Path(value)


def _read_str(env: Mapping[str, str], name: str, default: str) -> str:
    value = _read(env, name)
    return default if value is None else value


def _read_int(env: Mapping[str, str], name: str, default: int) -> int:
    value = _read(env, name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise SettingsError(f"{name} must be a whole number, got {value!r}") from None


def _read_float(env: Mapping[str, str], name: str, default: float) -> float:
    value = _read(env, name)
    if value is None:
        return default
    try:
        number = float(value)
    except ValueError:
        raise SettingsError(f"{name} must be a number, got {value!r}") from None
    if not math.isfinite(number):
        raise SettingsError(f"{name} must be a finite number, got {value!r}")
    return number


def _read_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    value = _read(env, name)
    if value is None:
        return default
    lowered = value.lower()
    if lowered in TRUE_VALUES:
        return True
    if lowered in FALSE_VALUES:
        return False
    raise SettingsError(f"{name} must be true or false, got {value!r}")


def _read_enum[E: StrEnum](env: Mapping[str, str], name: str, enum_type: type[E], default: E) -> E:
    value = _read(env, name)
    if value is None:
        return default
    for member in enum_type:
        if member.value.lower() == value.lower():
            return member
    allowed = ", ".join(member.value for member in enum_type)
    raise SettingsError(f"{name} must be one of {allowed}, got {value!r}")
