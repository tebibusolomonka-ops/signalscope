import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import InvalidInputError
from signalscope.domain.evaluation.model import EVALUATION_TASKS, EvaluationReportRecord

# Environment keys that may hold a local path, a secret or a credential are
# never stored. Only a small, safe summary is kept.
SAFE_ENVIRONMENT_KEYS = frozenset(
    {"python", "platform", "torch", "device", "cpu", "gpu", "package_versions"}
)


@dataclass(frozen=True, slots=True)
class ImportedReport:
    record: EvaluationReportRecord
    created: bool


class EvaluationReportImportService:
    """Validates an evaluation report and stores it once.

    The same report (by content hash) is never stored twice. Nothing from the
    report's environment is kept except a small safe summary: no paths, cache
    locations, tokens or credentials.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def import_report(
        self, report: dict[str, Any], imported_by_user_id: uuid.UUID | None = None
    ) -> ImportedReport:
        _validate(report)
        canonical = (
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode()
        sha256 = hashlib.sha256(canonical).hexdigest()
        existing = await self.session.scalar(
            select(EvaluationReportRecord).where(EvaluationReportRecord.report_sha256 == sha256)
        )
        if existing is not None:
            return ImportedReport(record=existing, created=False)
        try:
            record = EvaluationReportRecord(
                task=report["task"],
                model=report["model"],
                provider=report["provider"],
                dataset_name=str(report["dataset"].get("name", "")),
                dataset_fingerprint=report["dataset"]["fingerprint"],
                report_version=report["report_version"],
                report_json=report,
                report_sha256=sha256,
                environment_summary=_safe_environment(report.get("environment")),
                imported_by_user_id=imported_by_user_id,
            )
            self.session.add(record)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return ImportedReport(record=record, created=True)


def _validate(report: dict[str, Any]) -> None:
    try:
        if report["report_version"] != 1:
            raise ValueError("Unsupported evaluation report version.")
        if report["task"] not in EVALUATION_TASKS:
            raise ValueError("Unknown evaluation task.")
        if not all(
            isinstance(report[field], str) and report[field] for field in ("model", "provider")
        ):
            raise ValueError("Evaluation report is missing a model or provider.")
        if not isinstance(report["dataset"]["fingerprint"], str):
            raise ValueError("Evaluation report has no dataset fingerprint.")
        if not isinstance(report["metrics"], dict) or not isinstance(report["timings"], dict):
            raise ValueError("Evaluation report has no metrics or timings.")
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidInputError(f"Evaluation report is not valid: {error}") from error


def _safe_environment(environment: Any) -> dict[str, Any]:
    if not isinstance(environment, dict):
        return {}
    return {key: value for key, value in environment.items() if key in SAFE_ENVIRONMENT_KEYS}
