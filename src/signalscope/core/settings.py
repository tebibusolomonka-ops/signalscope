from dataclasses import dataclass
from enum import StrEnum


class SettingsError(ValueError):
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

    def __post_init__(self) -> None:
        if not self.app_name.strip():
            raise SettingsError("app_name must not be empty")
