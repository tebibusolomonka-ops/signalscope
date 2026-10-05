import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from signalscope.core.settings import Environment, Settings
from signalscope.domain.diagnostics.build_metadata import BuildMetadata
from signalscope.domain.diagnostics.deployment_validation import (
    BackupRequirement,
    DeploymentProfileError,
    DeploymentValidationProfile,
    DeploymentValidationService,
    ValidationStatus,
    VerifiedBackupEvidence,
    load_deployment_validation_profile,
)
from signalscope.domain.diagnostics.migration_compatibility import (
    MigrationCompatibilityReport,
    MigrationCompatibilityState,
)
from signalscope.domain.diagnostics.production_config import Level
from signalscope.domain.diagnostics.startup_preflight import (
    PreflightCheck,
    StartupPreflightReport,
)

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def settings(**changes: object) -> Settings:
    values: dict[str, object] = {
        "environment": Environment.PRODUCTION,
        "auth_enabled": True,
        "blob_dir": Path("/srv/blobs"),
    }
    values.update(changes)
    return Settings(**values)  # type: ignore[arg-type]


def profile(*, backup_required: bool | None = True) -> DeploymentValidationProfile:
    backup = (
        None
        if backup_required is None
        else BackupRequirement(required=backup_required, max_age_hours=24)
    )
    return DeploymentValidationProfile(1, True, True, True, True, True, backup)


def preflight(
    *, migration: MigrationCompatibilityState = MigrationCompatibilityState.CURRENT
) -> StartupPreflightReport:
    return StartupPreflightReport(
        checks=(PreflightCheck("storage", Level.PASS, "Storage answered."),),
        build=BuildMetadata("0.1.0", "3.12", None, None, None),
        migration=MigrationCompatibilityReport(migration, ("db",), ("app",), "Migration."),
    )


def backup(age_hours: int) -> VerifiedBackupEvidence:
    return VerifiedBackupEvidence(uuid.uuid4(), NOW - timedelta(hours=age_hours))


def statuses(result: object) -> dict[str, ValidationStatus]:
    return {item.requirement: item.status for item in result.results}  # type: ignore[attr-defined]


def test_all_requirements_pass() -> None:
    result = DeploymentValidationService(settings(), profile(), clock=lambda: NOW).validate(
        preflight(), backup(1)
    )

    assert result.passed is True
    assert set(statuses(result).values()) == {ValidationStatus.MET}


def test_failed_configuration_and_migration_are_missed() -> None:
    result = DeploymentValidationService(
        settings(auth_enabled=False, blob_dir=None), profile(), clock=lambda: NOW
    ).validate(preflight(migration=MigrationCompatibilityState.BEHIND), backup(1))

    assert result.passed is False
    assert statuses(result)["authentication"] is ValidationStatus.MISSED
    assert statuses(result)["migration_current"] is ValidationStatus.MISSED


def test_stale_required_backup_is_missed() -> None:
    result = DeploymentValidationService(settings(), profile(), clock=lambda: NOW).validate(
        preflight(), backup(25)
    )

    assert statuses(result)["recent_verified_backup"] is ValidationStatus.MISSED


def test_missing_optional_backup_is_warning() -> None:
    result = DeploymentValidationService(
        settings(), profile(backup_required=False), clock=lambda: NOW
    ).validate(preflight(), None)

    assert result.passed is True
    assert statuses(result)["recent_verified_backup"] is ValidationStatus.WARNING


def test_load_profile_and_reject_invalid_profile(tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text(
        json.dumps(
            {
                "version": 1,
                "requirements": {
                    "auth_required": True,
                    "recent_verified_backup": {"required": True, "max_age_hours": 24},
                },
            }
        ),
        encoding="utf-8",
    )
    assert load_deployment_validation_profile(valid).auth_required is True

    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"version": 2, "requirements": {}}', encoding="utf-8")
    with pytest.raises(DeploymentProfileError, match="version"):
        load_deployment_validation_profile(invalid)
