import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.api.middleware import SECURITY_HEADERS
from signalscope.api.security_policy import content_security_policy
from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.migration_compatibility import MigrationCompatibilityState
from signalscope.domain.diagnostics.production_config import Level
from signalscope.domain.diagnostics.startup_preflight import StartupPreflightReport
from signalscope.domain.organizations.backup_service import BACKUP_ARTIFACT_PREFIX
from signalscope.domain.organizations.export_record import (
    OrganizationExport,
    OrganizationExportStatus,
)
from signalscope.domain.sources.scheduling import Clock, utc_now

PROFILE_VERSION = 1


class DeploymentProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BackupRequirement:
    required: bool
    max_age_hours: int


@dataclass(frozen=True, slots=True)
class DeploymentValidationProfile:
    version: int
    auth_required: bool
    storage_required: bool
    migration_current_required: bool
    security_headers_required: bool
    csp_required: bool
    recent_verified_backup: BackupRequirement | None


@dataclass(frozen=True, slots=True)
class VerifiedBackupEvidence:
    backup_id: uuid.UUID
    finished_at: datetime

    def to_dict(self) -> dict[str, str]:
        return {"backup_id": str(self.backup_id), "finished_at": self.finished_at.isoformat()}


class ValidationStatus(StrEnum):
    MET = "met"
    MISSED = "missed"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class DeploymentRequirementResult:
    requirement: str
    status: ValidationStatus
    message: str


@dataclass(frozen=True, slots=True)
class DeploymentValidationResult:
    profile_version: int
    results: tuple[DeploymentRequirementResult, ...]
    backup: VerifiedBackupEvidence | None

    @property
    def passed(self) -> bool:
        return not any(result.status is ValidationStatus.MISSED for result in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_version": self.profile_version,
            "passed": self.passed,
            "requirements_met": [
                result.requirement
                for result in self.results
                if result.status is ValidationStatus.MET
            ],
            "requirements_missed": [
                result.requirement
                for result in self.results
                if result.status is ValidationStatus.MISSED
            ],
            "warnings": [
                {"requirement": result.requirement, "message": result.message}
                for result in self.results
                if result.status is ValidationStatus.WARNING
            ],
            "results": [
                {
                    "requirement": result.requirement,
                    "status": result.status.value,
                    "message": result.message,
                }
                for result in self.results
            ],
            "backup": None if self.backup is None else self.backup.to_dict(),
        }


def load_deployment_validation_profile(path: Path) -> DeploymentValidationProfile:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeploymentProfileError(f"Could not read deployment profile: {error}") from error
    if not isinstance(raw, dict) or raw.get("version") != PROFILE_VERSION:
        raise DeploymentProfileError("Deployment profile version must be 1.")
    requirements = raw.get("requirements")
    if not isinstance(requirements, dict):
        raise DeploymentProfileError("Deployment profile requirements must be an object.")
    allowed = {
        "auth_required",
        "storage_required",
        "migration_current_required",
        "security_headers_required",
        "csp_required",
        "recent_verified_backup",
    }
    unknown = set(requirements) - allowed
    if unknown:
        raise DeploymentProfileError(f"Unknown deployment requirement: {sorted(unknown)[0]}.")
    booleans: dict[str, bool] = {}
    for name in allowed - {"recent_verified_backup"}:
        value = requirements.get(name, False)
        if not isinstance(value, bool):
            raise DeploymentProfileError(f"{name} must be true or false.")
        booleans[name] = value
    backup_raw = requirements.get("recent_verified_backup")
    backup = None
    if backup_raw is not None:
        if not isinstance(backup_raw, dict) or set(backup_raw) != {"required", "max_age_hours"}:
            raise DeploymentProfileError(
                "recent_verified_backup must contain required and max_age_hours."
            )
        required = backup_raw["required"]
        max_age = backup_raw["max_age_hours"]
        if not isinstance(required, bool) or not isinstance(max_age, int) or max_age < 1:
            raise DeploymentProfileError("Backup requirement values are not valid.")
        backup = BackupRequirement(required, max_age)
    return DeploymentValidationProfile(
        version=PROFILE_VERSION,
        recent_verified_backup=backup,
        **booleans,
    )


class DeploymentValidationService:
    def __init__(
        self, settings: Settings, profile: DeploymentValidationProfile, *, clock: Clock = utc_now
    ) -> None:
        self._settings = settings
        self._profile = profile
        self._clock = clock

    def validate(
        self, preflight: StartupPreflightReport, backup: VerifiedBackupEvidence | None
    ) -> DeploymentValidationResult:
        results: list[DeploymentRequirementResult] = []
        if self._profile.auth_required:
            results.append(self._boolean("authentication", self._settings.auth_enabled))
        if self._profile.storage_required:
            storage_ready = any(
                check.check == "storage" and check.level is Level.PASS for check in preflight.checks
            )
            results.append(self._boolean("storage", storage_ready))
        if self._profile.migration_current_required:
            results.append(
                self._boolean(
                    "migration_current",
                    preflight.migration.state is MigrationCompatibilityState.CURRENT,
                )
            )
        if self._profile.security_headers_required:
            results.append(self._boolean("security_headers", bool(SECURITY_HEADERS)))
        if self._profile.csp_required:
            results.append(
                self._boolean(
                    "content_security_policy", bool(content_security_policy(self._settings))
                )
            )
        requirement = self._profile.recent_verified_backup
        if requirement is not None:
            results.append(self._backup(requirement, backup))
        return DeploymentValidationResult(self._profile.version, tuple(results), backup)

    @staticmethod
    def _boolean(requirement: str, met: bool) -> DeploymentRequirementResult:
        status = ValidationStatus.MET if met else ValidationStatus.MISSED
        return DeploymentRequirementResult(
            requirement, status, "Requirement is met." if met else "Requirement is not met."
        )

    def _backup(
        self, requirement: BackupRequirement, backup: VerifiedBackupEvidence | None
    ) -> DeploymentRequirementResult:
        if backup is None:
            status = ValidationStatus.MISSED if requirement.required else ValidationStatus.WARNING
            return DeploymentRequirementResult(
                "recent_verified_backup", status, "No verified backup was found."
            )
        fresh = self._clock() - backup.finished_at <= timedelta(hours=requirement.max_age_hours)
        if fresh:
            return DeploymentRequirementResult(
                "recent_verified_backup", ValidationStatus.MET, "Verified backup is recent."
            )
        status = ValidationStatus.MISSED if requirement.required else ValidationStatus.WARNING
        return DeploymentRequirementResult(
            "recent_verified_backup", status, "Latest verified backup is stale."
        )


async def latest_verified_backup(session: AsyncSession) -> VerifiedBackupEvidence | None:
    export = await session.scalar(
        select(OrganizationExport)
        .where(
            OrganizationExport.status == OrganizationExportStatus.COMPLETED,
            OrganizationExport.artifact_key.startswith(BACKUP_ARTIFACT_PREFIX),
            OrganizationExport.sha256.is_not(None),
            OrganizationExport.finished_at.is_not(None),
        )
        .order_by(OrganizationExport.finished_at.desc(), OrganizationExport.id.desc())
        .limit(1)
    )
    if export is None or export.finished_at is None:
        return None
    return VerifiedBackupEvidence(export.id, export.finished_at)
