import json
from pathlib import Path

from signalscope.core.settings import Environment, Settings
from signalscope.domain.diagnostics.pilot_readiness import (
    CheckStatus,
    PilotReadinessEvaluator,
)

PASSWORD = "pilot-secret-pw"


def good_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": Environment.PRODUCTION,
        "auth_enabled": True,
        "database_url": f"postgresql+asyncpg://admin:{PASSWORD}@db.internal/signalscope",
        "blob_dir": Path("/srv/blobs"),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def checks(settings: Settings) -> dict[str, CheckStatus]:
    report = PilotReadinessEvaluator(settings).evaluate_without_database()
    return {check.name: check.status for check in report.checks if check.name != "manual"}


def test_complete_configuration_is_ready() -> None:
    report = PilotReadinessEvaluator(good_settings()).evaluate_without_database()

    assert report.ready is True
    assert checks(good_settings())["authentication"] is CheckStatus.PASSED
    assert checks(good_settings())["security_headers"] is CheckStatus.PASSED
    assert checks(good_settings())["content_security_policy"] is CheckStatus.PASSED


def test_auth_disabled_fails_the_pilot() -> None:
    report = PilotReadinessEvaluator(good_settings(auth_enabled=False)).evaluate_without_database()

    assert report.ready is False
    assert checks(good_settings(auth_enabled=False))["authentication"] is CheckStatus.FAILED


def test_missing_backup_storage_is_flagged() -> None:
    result = checks(good_settings(blob_dir=None))

    assert result["storage"] is CheckStatus.FAILED
    assert result["backup"] is CheckStatus.WARNING


def test_manual_checks_are_listed() -> None:
    report = PilotReadinessEvaluator(good_settings()).evaluate_without_database()

    manual = [check for check in report.checks if check.status is CheckStatus.MANUAL]
    assert len(manual) >= 3


def test_model_evidence_missing_does_not_fail_the_pilot() -> None:
    report = PilotReadinessEvaluator(good_settings()).evaluate_without_database()

    assert report.ready is True
    assert report.model_section["configured"] is False
    # Model readiness is reported separately and is never a failed check.
    assert not any(check.name.startswith("model") for check in report.checks)


def test_output_has_no_secret() -> None:
    report = PilotReadinessEvaluator(good_settings(auth_enabled=False)).evaluate_without_database()

    assert PASSWORD not in json.dumps(report.to_dict())
