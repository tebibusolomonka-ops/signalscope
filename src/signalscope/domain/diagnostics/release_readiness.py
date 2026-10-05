import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.acceptance import (
    AcceptanceEvidence,
    AcceptanceResult,
    AcceptanceRunner,
)
from signalscope.domain.diagnostics.acceptance_profile import AcceptanceProfile
from signalscope.domain.diagnostics.build_metadata import BuildMetadataService
from signalscope.domain.diagnostics.deployment_validation import (
    DeploymentValidationProfile,
    DeploymentValidationResult,
    DeploymentValidationService,
    latest_verified_backup,
)
from signalscope.domain.diagnostics.disaster_recovery_acceptance import (
    DisasterRecoveryAcceptanceService,
)
from signalscope.domain.diagnostics.pilot_readiness import (
    PilotReadinessEvaluator,
    PilotReadinessReport,
)
from signalscope.domain.diagnostics.security_acceptance import (
    SecurityDeploymentAcceptanceService,
)
from signalscope.domain.diagnostics.startup_preflight import (
    StartupPreflightReport,
    StartupPreflightService,
)
from signalscope.domain.diagnostics.support_bundle import SupportBundleService
from signalscope.domain.evaluation.model import EvaluationReportRecord
from signalscope.storage.blob import BlobStore


@dataclass(frozen=True, slots=True)
class ModelEvaluationEvidence:
    report_id: uuid.UUID
    task: str
    model: str
    provider: str
    dataset_fingerprint: str
    created_at: str
    quality_gate_evidence_available: bool
    quality_gate_passed: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": str(self.report_id),
            "task": self.task,
            "model": self.model,
            "provider": self.provider,
            "dataset_fingerprint": self.dataset_fingerprint,
            "created_at": self.created_at,
            "quality_gate_evidence_available": self.quality_gate_evidence_available,
            "quality_gate_passed": self.quality_gate_passed,
        }


@dataclass(frozen=True, slots=True)
class ReleaseReadinessReport:
    preflight: StartupPreflightReport
    deployment_validation: DeploymentValidationResult | None
    pilot_readiness: PilotReadinessReport
    acceptance: AcceptanceResult
    model_evaluations: tuple[ModelEvaluationEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        acceptance = self.acceptance.to_dict()
        evidence = acceptance["evidence"]
        assert isinstance(evidence, dict)
        return {
            "build_metadata": self.preflight.build.to_dict(),
            "startup_preflight": self.preflight.to_dict(),
            "migration_compatibility": self.preflight.migration.to_dict(),
            "deployment_validation": (
                None if self.deployment_validation is None else self.deployment_validation.to_dict()
            ),
            "pilot_readiness": self.pilot_readiness.to_dict(),
            "acceptance": acceptance,
            "latest_verified_backup_evidence": evidence.get("backup"),
            "disaster_recovery_evidence": evidence.get("disaster_recovery"),
            "model_evaluation_evidence": {
                "available": bool(self.model_evaluations),
                "reports": [report.to_dict() for report in self.model_evaluations],
            },
            "evidence_references": acceptance["evidence_references"],
        }


class ReleaseReadinessService:
    """Collect release evidence without deploying or changing application state."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def collect(
        self,
        profile: AcceptanceProfile,
        *,
        session: AsyncSession | None,
        blobs: BlobStore | None,
        organization_id: uuid.UUID | None = None,
        deployment_profile: DeploymentValidationProfile | None = None,
    ) -> ReleaseReadinessReport:
        preflight_service = StartupPreflightService(self._settings)
        dr_evidence = AcceptanceEvidence({}, {})
        deployment_backup = None
        if session is None:
            preflight = preflight_service.without_database()
            pilot = PilotReadinessEvaluator(self._settings).evaluate_without_database()
            support_available = bool(SupportBundleService(self._settings).build_without_database())
            model_evaluations: tuple[ModelEvaluationEvidence, ...] = ()
        else:
            preflight = await preflight_service.collect(session, blobs)
            pilot = await PilotReadinessEvaluator(self._settings).evaluate(session, blobs)
            support_available = bool(
                await SupportBundleService(self._settings).build(session, blobs)
            )
            deployment_backup = await latest_verified_backup(session)
            if organization_id is not None:
                dr_evidence = await DisasterRecoveryAcceptanceService(session).collect(
                    organization_id, profile
                )
            model_evaluations = await model_evaluation_evidence(session)

        deployment = (
            None
            if deployment_profile is None
            else DeploymentValidationService(self._settings, deployment_profile).validate(
                preflight, deployment_backup
            )
        )
        security = SecurityDeploymentAcceptanceService(self._settings).collect(
            preflight,
            deployment_validation=deployment,
            support_bundle_available=support_available,
        )
        values: dict[str, bool | None] = {
            "operations.startup_preflight_passes": preflight.passed,
            "model_evaluation.quality_gate_evidence_exists": any(
                report.quality_gate_evidence_available for report in model_evaluations
            ),
        }
        values.update(security.values)
        values.update(dr_evidence.values)
        references = dict(security.references)
        references.update(dr_evidence.references)
        build = BuildMetadataService(self._settings).inspect()
        if build.build_sha is not None:
            references["build_sha"] = build.build_sha
        facts = {
            **(security.facts or {}),
            **(dr_evidence.facts or {}),
        }
        acceptance = AcceptanceRunner().run(
            profile,
            AcceptanceEvidence(
                values,
                references,
                security.warnings + dr_evidence.warnings,
                facts,
            ),
        )
        return ReleaseReadinessReport(
            preflight,
            deployment,
            pilot,
            acceptance,
            model_evaluations,
        )


async def model_evaluation_evidence(
    session: AsyncSession,
) -> tuple[ModelEvaluationEvidence, ...]:
    records = list(
        await session.scalars(
            select(EvaluationReportRecord).order_by(
                EvaluationReportRecord.created_at.desc(),
                EvaluationReportRecord.id.desc(),
            )
        )
    )
    evidence = []
    for record in records:
        available, passed = _quality_gate_evidence(record.report_json)
        evidence.append(
            ModelEvaluationEvidence(
                record.id,
                record.task,
                record.model,
                record.provider,
                record.dataset_fingerprint,
                record.created_at.isoformat(),
                available,
                passed,
            )
        )
    return tuple(evidence)


def _quality_gate_evidence(report: dict[str, Any]) -> tuple[bool, bool | None]:
    for key in ("quality_gate_result", "quality_gate", "quality_gates"):
        value = report.get(key)
        if isinstance(value, dict):
            passed = value.get("passed")
            return True, passed if isinstance(passed, bool) else None
        if isinstance(value, list):
            passed_values = [
                item.get("passed")
                for item in value
                if isinstance(item, dict) and isinstance(item.get("passed"), bool)
            ]
            return True, all(passed_values) if passed_values else None
    return False, None
