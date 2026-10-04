import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class EvaluationReportSummaryRead(BaseModel):
    """One stored evaluation report, without the full report body."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task: str
    model: str
    provider: str
    dataset_name: str
    dataset_fingerprint: str
    report_version: int
    created_at: datetime


class EvaluationReportDetailRead(EvaluationReportSummaryRead):
    """A stored report with its metrics, timings and safe environment summary."""

    report_json: dict[str, Any]
    environment_summary: dict[str, Any]


class EvaluationReportImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: dict[str, Any]


class EvaluationComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_ids: list[uuid.UUID]
