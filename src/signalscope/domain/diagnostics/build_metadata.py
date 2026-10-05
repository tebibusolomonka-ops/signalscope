import importlib.metadata
import platform
from collections.abc import Callable
from dataclasses import asdict, dataclass

from signalscope.core.settings import Settings


@dataclass(frozen=True, slots=True)
class BuildMetadata:
    application_version: str
    python_version: str
    build_sha: str | None
    build_time: str | None
    release_name: str | None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


class BuildMetadataService:
    def __init__(
        self,
        settings: Settings,
        *,
        version_lookup: Callable[[str], str] = importlib.metadata.version,
        python_version: Callable[[], str] = platform.python_version,
    ) -> None:
        self._settings = settings
        self._version_lookup = version_lookup
        self._python_version = python_version

    def inspect(self) -> BuildMetadata:
        try:
            application_version = self._version_lookup("signalscope")
        except importlib.metadata.PackageNotFoundError:
            application_version = "unknown"
        return BuildMetadata(
            application_version=application_version,
            python_version=self._python_version(),
            build_sha=self._settings.build_sha,
            build_time=self._settings.build_time,
            release_name=self._settings.release_name,
        )
