from dataclasses import dataclass
from enum import StrEnum

from signalscope.core.settings import Environment, Settings


class Level(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ConfigFinding:
    check: str
    level: Level
    message: str


@dataclass(frozen=True, slots=True)
class ConfigValidationResult:
    findings: tuple[ConfigFinding, ...]

    @property
    def has_errors(self) -> bool:
        return any(finding.level is Level.ERROR for finding in self.findings)


class ProductionConfigurationValidator:
    """Check settings for production without printing any secret.

    It reads only configuration flags and never the database URL, so a password
    in that URL can never reach the output. Local models are optional and never
    required.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def validate(self) -> ConfigValidationResult:
        findings: list[ConfigFinding] = [
            self._environment(),
            self._debug(),
            self._auth(),
            self._database(),
            self._storage(),
            self._backup(),
            self._same_origin(),
        ]
        return ConfigValidationResult(findings=tuple(findings))

    def _environment(self) -> ConfigFinding:
        if self.settings.environment is Environment.PRODUCTION:
            return ConfigFinding("environment", Level.PASS, "Environment is production.")
        return ConfigFinding(
            "environment",
            Level.WARNING,
            f"Environment is {self.settings.environment.value}, not production.",
        )

    def _debug(self) -> ConfigFinding:
        if self.settings.debug:
            return ConfigFinding("debug", Level.ERROR, "Debug mode is on.")
        return ConfigFinding("debug", Level.PASS, "Debug mode is off.")

    def _auth(self) -> ConfigFinding:
        if self.settings.auth_enabled:
            return ConfigFinding("authentication", Level.PASS, "Authentication is enabled.")
        return ConfigFinding("authentication", Level.ERROR, "Authentication is disabled.")

    def _database(self) -> ConfigFinding:
        if self.settings.database_url is None:
            return ConfigFinding("database", Level.ERROR, "Database URL is not configured.")
        if _looks_like_test_database(self.settings.database_url):
            return ConfigFinding(
                "database", Level.ERROR, "Database name ends with _test; not for production."
            )
        return ConfigFinding("database", Level.PASS, "A database is configured.")

    def _storage(self) -> ConfigFinding:
        if self.settings.blob_dir is None:
            return ConfigFinding("storage", Level.ERROR, "File storage is not configured.")
        return ConfigFinding("storage", Level.PASS, "File storage is configured.")

    def _backup(self) -> ConfigFinding:
        if self.settings.database_url is not None and self.settings.blob_dir is not None:
            return ConfigFinding("backup", Level.PASS, "Backups can run.")
        return ConfigFinding("backup", Level.WARNING, "Backups need a database and file storage.")

    def _same_origin(self) -> ConfigFinding:
        return ConfigFinding(
            "same_origin", Level.PASS, "The API and web app are served from the same origin."
        )


def _looks_like_test_database(database_url: str) -> bool:
    name = database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    return name.endswith("_test")
