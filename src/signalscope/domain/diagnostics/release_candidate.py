import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.api.middleware import SECURITY_HEADERS
from signalscope.api.security_policy import content_security_policy
from signalscope.core.settings import Environment, Settings
from signalscope.domain.diagnostics.build_metadata import BuildMetadata
from signalscope.domain.diagnostics.deployment_validation import (
    DeploymentValidationResult,
    VerifiedBackupEvidence,
)
from signalscope.domain.evaluation.model import EvaluationReportRecord
from signalscope.domain.sources.scheduling import Clock, utc_now

MANIFEST_VERSION = 1


@dataclass(frozen=True, slots=True)
class EvaluationEvidenceReference:
    report_id: uuid.UUID
    task: str
    dataset_fingerprint: str
    report_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "report_id": str(self.report_id),
            "task": self.task,
            "dataset_fingerprint": self.dataset_fingerprint,
            "report_sha256": self.report_sha256,
        }


@dataclass(frozen=True, slots=True)
class ReleaseCandidateManifest:
    created_at: datetime
    build: BuildMetadata
    migration_head: str | None
    deployment_validation: DeploymentValidationResult
    backup: VerifiedBackupEvidence | None
    evaluation_reports: tuple[EvaluationEvidenceReference, ...]
    security: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": MANIFEST_VERSION,
            "created_at": self.created_at.isoformat(),
            "build": self.build.to_dict(),
            "migration_head": self.migration_head,
            "deployment_validation": self.deployment_validation.to_dict(),
            "latest_verified_backup": None if self.backup is None else self.backup.to_dict(),
            "evaluation_reports": [report.to_dict() for report in self.evaluation_reports],
            "security": self.security,
        }


class ReleaseCandidateService:
    def __init__(self, settings: Settings, *, clock: Clock = utc_now) -> None:
        self._settings = settings
        self._clock = clock

    def create(
        self,
        *,
        build: BuildMetadata,
        migration_head: str | None,
        validation: DeploymentValidationResult,
        backup: VerifiedBackupEvidence | None,
        evaluation_reports: tuple[EvaluationEvidenceReference, ...],
    ) -> ReleaseCandidateManifest:
        reports = tuple(sorted(evaluation_reports, key=lambda item: str(item.report_id)))
        return ReleaseCandidateManifest(
            created_at=self._clock(),
            build=build,
            migration_head=migration_head,
            deployment_validation=validation,
            backup=backup,
            evaluation_reports=reports,
            security={
                "security_headers_enabled": bool(SECURITY_HEADERS),
                "security_header_names": sorted(SECURITY_HEADERS),
                "content_security_policy_enabled": bool(content_security_policy(self._settings)),
                "production_policy": self._settings.environment is Environment.PRODUCTION,
            },
        )


async def evaluation_evidence_references(
    session: AsyncSession, report_ids: list[uuid.UUID]
) -> tuple[EvaluationEvidenceReference, ...]:
    if not report_ids:
        return ()
    records = list(
        await session.scalars(
            select(EvaluationReportRecord).where(EvaluationReportRecord.id.in_(report_ids))
        )
    )
    found = {record.id for record in records}
    missing = sorted(str(report_id) for report_id in set(report_ids) - found)
    if missing:
        raise ValueError(f"Evaluation report was not found: {missing[0]}")
    return tuple(
        EvaluationEvidenceReference(
            record.id,
            record.task,
            record.dataset_fingerprint,
            record.report_sha256,
        )
        for record in records
    )
