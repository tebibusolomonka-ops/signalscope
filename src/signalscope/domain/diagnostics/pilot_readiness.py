from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.api.middleware import SECURITY_HEADERS
from signalscope.api.security_policy import content_security_policy
from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.deployment import _migration_current, alembic_migration_head
from signalscope.domain.diagnostics.production_config import Level, ProductionConfigurationValidator
from signalscope.domain.diagnostics.readiness import ComponentState, DependencyReadinessService
from signalscope.domain.evaluation.model import EvaluationReportRecord
from signalscope.storage.blob import BlobStore

# Operator steps the evaluator cannot check by itself.
MANUAL_CHECKS = (
    "Confirm HTTPS/TLS terminates in front of the API.",
    "Confirm a system administrator account exists with a strong password.",
    "Confirm backups are copied to separate storage and a restore was rehearsed.",
)

_CONFIG_LEVEL_TO_STATUS = {
    Level.PASS: "passed",
    Level.WARNING: "warning",
    Level.ERROR: "failed",
}


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class PilotCheck:
    name: str
    status: CheckStatus
    message: str


@dataclass(frozen=True, slots=True)
class PilotReadinessReport:
    checks: tuple[PilotCheck, ...]
    model_section: dict[str, Any]

    def _by(self, status: CheckStatus) -> list[PilotCheck]:
        return [check for check in self.checks if check.status is status]

    @property
    def ready(self) -> bool:
        """Ready when no check failed. Missing model evidence never fails a pilot."""
        return not self._by(CheckStatus.FAILED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "passed": [c.name for c in self._by(CheckStatus.PASSED)],
            "failed": [
                {"name": c.name, "message": c.message} for c in self._by(CheckStatus.FAILED)
            ],
            "warnings": [
                {"name": c.name, "message": c.message} for c in self._by(CheckStatus.WARNING)
            ],
            "manual": [c.message for c in self._by(CheckStatus.MANUAL)],
            "model": self.model_section,
        }


class PilotReadinessEvaluator:
    """A factual pilot readiness checklist. It is not a score.

    Local model evidence is reported in its own section and never fails the
    pilot on its own. The evaluator reads configuration and counts only, so it
    exposes no secret and no tenant content.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def evaluate(
        self, session: AsyncSession, blobs: BlobStore | None
    ) -> PilotReadinessReport:
        checks = list(self._config_checks())
        checks.extend(await self._dependency_checks(session, blobs))
        checks.append(await self._migration_check(session))
        checks.extend(self._deployment_checks())
        checks.extend(self._manual_checks())
        model = await self._model_section(session)
        return PilotReadinessReport(checks=tuple(checks), model_section=model)

    def evaluate_without_database(self) -> PilotReadinessReport:
        checks = list(self._config_checks())
        checks.extend(self._deployment_checks())
        checks.extend(self._manual_checks())
        model = {"configured": self._models_configured(), "evaluation_evidence_available": None}
        return PilotReadinessReport(checks=tuple(checks), model_section=model)

    def _config_checks(self) -> list[PilotCheck]:
        result = ProductionConfigurationValidator(self.settings).validate()
        return [
            PilotCheck(
                finding.check, CheckStatus(_CONFIG_LEVEL_TO_STATUS[finding.level]), finding.message
            )
            for finding in result.findings
        ]

    async def _dependency_checks(
        self, session: AsyncSession, blobs: BlobStore | None
    ) -> list[PilotCheck]:
        report = await DependencyReadinessService(session, self.settings, blobs).check()
        checks: list[PilotCheck] = []
        for component in report.components:
            if component.name.startswith("model_"):
                continue
            if component.state is ComponentState.UNAVAILABLE:
                status = CheckStatus.FAILED
            elif component.state is ComponentState.DEGRADED:
                status = CheckStatus.WARNING
            else:
                status = CheckStatus.PASSED
            checks.append(PilotCheck(f"readiness_{component.name}", status, component.detail))
        return checks

    async def _migration_check(self, session: AsyncSession) -> PilotCheck:
        current = await _migration_current(session)
        head = alembic_migration_head()
        if current is not None and current == head:
            return PilotCheck(
                "migration", CheckStatus.PASSED, "The database is at the latest migration."
            )
        return PilotCheck(
            "migration", CheckStatus.FAILED, "The database is not at the latest migration."
        )

    def _deployment_checks(self) -> list[PilotCheck]:
        checks = []
        if SECURITY_HEADERS:
            checks.append(
                PilotCheck(
                    "security_headers", CheckStatus.PASSED, "Security headers are configured."
                )
            )
        if content_security_policy(self.settings):
            checks.append(
                PilotCheck("content_security_policy", CheckStatus.PASSED, "A CSP is configured.")
            )
        return checks

    def _manual_checks(self) -> list[PilotCheck]:
        return [PilotCheck("manual", CheckStatus.MANUAL, step) for step in MANUAL_CHECKS]

    async def _model_section(self, session: AsyncSession) -> dict[str, Any]:
        try:
            count = await session.scalar(select(func.count()).select_from(EvaluationReportRecord))
        except SQLAlchemyError:
            count = None
        return {
            "configured": self._models_configured(),
            "evaluation_reports": count,
            "evaluation_evidence_available": None if count is None else count > 0,
        }

    def _models_configured(self) -> bool:
        return any(
            getattr(self.settings, flag)
            for flag in (
                "local_embeddings_enabled",
                "local_reranking_enabled",
                "local_entities_enabled",
                "local_structured_enabled",
                "local_answers_enabled",
            )
        )
