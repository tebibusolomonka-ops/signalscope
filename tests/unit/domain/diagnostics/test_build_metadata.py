import importlib.metadata

from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.build_metadata import BuildMetadataService


def test_configured_build_metadata() -> None:
    settings = Settings(
        build_sha="abc123",
        build_time="2026-10-05T10:00:00Z",
        release_name="October release",
    )

    metadata = BuildMetadataService(
        settings,
        version_lookup=lambda _: "1.2.3",
        python_version=lambda: "3.12.10",
    ).inspect()

    assert metadata.to_dict() == {
        "application_version": "1.2.3",
        "python_version": "3.12.10",
        "build_sha": "abc123",
        "build_time": "2026-10-05T10:00:00Z",
        "release_name": "October release",
    }


def test_optional_build_metadata_can_be_missing() -> None:
    metadata = BuildMetadataService(
        Settings(),
        version_lookup=lambda _: "0.1.0",
        python_version=lambda: "3.12.10",
    ).inspect()

    assert metadata.build_sha is None
    assert metadata.build_time is None
    assert metadata.release_name is None


def test_missing_distribution_has_an_explicit_version() -> None:
    def missing(_: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    metadata = BuildMetadataService(Settings(), version_lookup=missing).inspect()

    assert metadata.application_version == "unknown"


def test_build_metadata_does_not_expose_secrets() -> None:
    secret = "postgresql+asyncpg://user:secret@database/signalscope"
    metadata = BuildMetadataService(
        Settings(database_url=secret),
        version_lookup=lambda _: "0.1.0",
    ).inspect()

    assert secret not in str(metadata.to_dict())
