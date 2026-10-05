import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.diagnostics.acceptance import AcceptanceEvidence
from signalscope.domain.diagnostics.acceptance_profile import AcceptanceProfile
from signalscope.domain.organizations.backup_policy import OrganizationBackupPolicy
from signalscope.domain.organizations.backup_service import BACKUP_ARTIFACT_PREFIX
from signalscope.domain.organizations.drill_record import (
    DisasterRecoveryDrillMode,
    DisasterRecoveryDrillStatus,
    OrganizationDisasterRecoveryDrill,
)
from signalscope.domain.organizations.export_record import (
    OrganizationExport,
    OrganizationExportStatus,
)
from signalscope.domain.sources.scheduling import Clock, utc_now


@dataclass(frozen=True, slots=True)
class VerifiedOrganizationBackup:
    id: uuid.UUID
    created_at: datetime
    finished_at: datetime
    sha256: str
    include_assets: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "verification_status": "verified",
            "include_assets": self.include_assets,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class SuccessfulDisasterRecoveryDrill:
    id: uuid.UUID
    mode: DisasterRecoveryDrillMode
    status: DisasterRecoveryDrillStatus
    started_at: datetime
    finished_at: datetime
    source_organization_id: uuid.UUID
    target_organization_id: uuid.UUID | None
    asset_verification_succeeded: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "mode": self.mode.value,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "source_organization_id": str(self.source_organization_id),
            "target_organization_id": (
                str(self.target_organization_id)
                if self.target_organization_id is not None
                else None
            ),
            "asset_verification_succeeded": self.asset_verification_succeeded,
        }


@dataclass(frozen=True, slots=True)
class DisasterRecoveryRecords:
    backup: VerifiedOrganizationBackup | None
    verification_drill: SuccessfulDisasterRecoveryDrill | None
    restore_test_drill: SuccessfulDisasterRecoveryDrill | None


class DisasterRecoveryAcceptanceService:
    """Read organization-scoped backup and drill evidence without changing it."""

    def __init__(self, session: AsyncSession, clock: Clock = utc_now) -> None:
        self._session = session
        self._clock = clock

    async def collect(
        self, organization_id: uuid.UUID, profile: AcceptanceProfile
    ) -> AcceptanceEvidence:
        policy = await self._session.get(OrganizationBackupPolicy, organization_id)
        backup_record = await self._session.scalar(
            select(OrganizationExport)
            .where(
                OrganizationExport.organization_id == organization_id,
                OrganizationExport.status == OrganizationExportStatus.COMPLETED,
                OrganizationExport.artifact_key.startswith(BACKUP_ARTIFACT_PREFIX),
                OrganizationExport.sha256.is_not(None),
                OrganizationExport.finished_at.is_not(None),
            )
            .order_by(OrganizationExport.finished_at.desc(), OrganizationExport.id.desc())
            .limit(1)
        )
        backup = None
        if (
            backup_record is not None
            and backup_record.finished_at is not None
            and backup_record.sha256 is not None
        ):
            backup = VerifiedOrganizationBackup(
                backup_record.id,
                backup_record.created_at,
                backup_record.finished_at,
                backup_record.sha256,
                policy.include_assets if policy is not None else None,
            )
        verification = await self._latest_drill(
            organization_id, DisasterRecoveryDrillMode.VERIFICATION_ONLY
        )
        restore_test = await self._latest_drill(
            organization_id, DisasterRecoveryDrillMode.RESTORE_TEST
        )
        return evaluate_disaster_recovery_acceptance(
            profile,
            DisasterRecoveryRecords(backup, verification, restore_test),
            self._clock(),
        )

    async def _latest_drill(
        self, organization_id: uuid.UUID, mode: DisasterRecoveryDrillMode
    ) -> SuccessfulDisasterRecoveryDrill | None:
        record = await self._session.scalar(
            select(OrganizationDisasterRecoveryDrill)
            .where(
                OrganizationDisasterRecoveryDrill.organization_id == organization_id,
                OrganizationDisasterRecoveryDrill.mode == mode,
                OrganizationDisasterRecoveryDrill.status == DisasterRecoveryDrillStatus.COMPLETED,
                OrganizationDisasterRecoveryDrill.finished_at.is_not(None),
            )
            .order_by(
                OrganizationDisasterRecoveryDrill.finished_at.desc(),
                OrganizationDisasterRecoveryDrill.id.desc(),
            )
            .limit(1)
        )
        if record is None or record.finished_at is None:
            return None
        include_assets = record.summary.get("include_assets") is True
        asset_count = record.summary.get("asset_count")
        assets_verified = include_assets or (
            isinstance(asset_count, int) and not isinstance(asset_count, bool) and asset_count > 0
        )
        return SuccessfulDisasterRecoveryDrill(
            record.id,
            record.mode,
            record.status,
            record.started_at,
            record.finished_at,
            record.organization_id,
            record.target_organization_id,
            assets_verified,
        )


def evaluate_disaster_recovery_acceptance(
    profile: AcceptanceProfile,
    records: DisasterRecoveryRecords,
    now: datetime,
) -> AcceptanceEvidence:
    backup_requirements = profile.section("backup") or {}
    drill_requirements = profile.section("disaster_recovery") or {}
    backup_age = _integer(backup_requirements.get("max_age_hours"))
    verification_age = _integer(
        drill_requirements.get("verification_max_age_hours")
        or drill_requirements.get("max_age_hours")
    )
    restore_age = _integer(drill_requirements.get("restore_test_max_age_hours"))

    backup_ok = records.backup is not None and _fresh(records.backup.finished_at, backup_age, now)
    verification_ok = records.verification_drill is not None and _fresh(
        records.verification_drill.finished_at, verification_age, now
    )
    restore_ok = records.restore_test_drill is not None and _fresh(
        records.restore_test_drill.finished_at, restore_age, now
    )
    drills = (records.verification_drill, records.restore_test_drill)
    assets_ok = any(drill.asset_verification_succeeded for drill in drills if drill is not None)

    values: dict[str, bool | None] = {
        "backup.verified_backup_exists": backup_ok,
        "disaster_recovery.drill_exists": verification_ok,
        "disaster_recovery.verification_drill_exists": verification_ok,
        "disaster_recovery.restore_test_required": restore_ok,
        "disaster_recovery.asset_verification_succeeded": assets_ok,
    }
    references: dict[str, str] = {}
    facts: dict[str, Any] = {
        "backup": records.backup.to_dict() if records.backup is not None else None,
        "disaster_recovery": {
            "verification_drill": (
                records.verification_drill.to_dict()
                if records.verification_drill is not None
                else None
            ),
            "restore_test_drill": (
                records.restore_test_drill.to_dict()
                if records.restore_test_drill is not None
                else None
            ),
        },
    }
    if records.backup is not None:
        references["backup_export_id"] = str(records.backup.id)
    if records.verification_drill is not None:
        references["verification_drill_id"] = str(records.verification_drill.id)
    if records.restore_test_drill is not None:
        references["restore_test_drill_id"] = str(records.restore_test_drill.id)
    return AcceptanceEvidence(values, references, facts=facts)


def _fresh(finished_at: datetime, max_age_hours: int | None, now: datetime) -> bool:
    return max_age_hours is None or now - finished_at <= timedelta(hours=max_age_hours)


def _integer(value: bool | int | None) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
