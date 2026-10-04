from pathlib import Path

from signalscope.core.settings import Environment, Settings
from signalscope.domain.diagnostics.production_config import (
    Level,
    ProductionConfigurationValidator,
)

PASSWORD = "sup3r-secret-pw"


def good_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": Environment.PRODUCTION,
        "debug": False,
        "auth_enabled": True,
        "database_url": f"postgresql+asyncpg://admin:{PASSWORD}@db.internal/signalscope",
        "blob_dir": Path("/srv/blobs"),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def levels(settings: Settings) -> dict[str, Level]:
    result = ProductionConfigurationValidator(settings).validate()
    return {finding.check: finding.level for finding in result.findings}


def test_good_configuration_has_no_errors() -> None:
    result = ProductionConfigurationValidator(good_settings()).validate()

    assert result.has_errors is False
    assert levels(good_settings())["database"] is Level.PASS


def test_disabled_authentication_is_an_error() -> None:
    result = ProductionConfigurationValidator(good_settings(auth_enabled=False)).validate()

    assert result.has_errors is True
    assert levels(good_settings(auth_enabled=False))["authentication"] is Level.ERROR


def test_test_database_is_an_error() -> None:
    settings = good_settings(
        database_url="postgresql+asyncpg://admin:pw@db.internal/signalscope_test"
    )

    assert levels(settings)["database"] is Level.ERROR


def test_missing_storage_is_an_error() -> None:
    assert levels(good_settings(blob_dir=None))["storage"] is Level.ERROR


def test_debug_mode_is_an_error() -> None:
    assert levels(good_settings(debug=True))["debug"] is Level.ERROR


def test_non_production_environment_is_a_warning_not_error() -> None:
    settings = good_settings(environment=Environment.DEVELOPMENT)
    result = ProductionConfigurationValidator(settings).validate()

    assert levels(settings)["environment"] is Level.WARNING
    assert result.has_errors is False


def test_findings_never_include_the_database_password() -> None:
    result = ProductionConfigurationValidator(good_settings()).validate()

    for finding in result.findings:
        assert PASSWORD not in finding.message
