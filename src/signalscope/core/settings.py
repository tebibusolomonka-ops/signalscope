import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from signalscope.core.errors import SignalScopeError

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})
DATABASE_URL_PREFIX = "postgresql+asyncpg://"


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

    def __post_init__(self) -> None:
        if not self.app_name.strip():
            raise SettingsError("app_name must not be empty")
        if not self.local_embedding_device.strip():
            raise SettingsError("local_embedding_device must not be empty")
        if self.local_embedding_batch_size < 1:
            raise SettingsError("local_embedding_batch_size must be at least 1")
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
