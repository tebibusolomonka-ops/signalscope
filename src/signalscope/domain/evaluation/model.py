import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import UUIDPrimaryKeyMixin
from signalscope.domain.documents.chunk import EMPTY_JSON_OBJECT

# The evaluation tasks whose reports can be kept. These match the report
# "task" values produced by the benchmark tooling.
EVALUATION_TASKS = (
    "embedding_retrieval",
    "reranking",
    "structured_extraction",
    "answer_citation",
    "relation_evaluation",
)
TASK_MAX_LENGTH = 40
NAME_MAX_LENGTH = 200
FINGERPRINT_MAX_LENGTH = 128
SHA256_LENGTH = 64


class EvaluationReportRecord(UUIDPrimaryKeyMixin, Base):
    """A measured evaluation report kept for review.

    The report JSON holds metrics, timings and a safe environment summary, as
    produced by the benchmark tooling. It never holds model weights, prompts
    with tenant document text, tokens, credentials or cache paths. These are
    system records, not tenant content, so there is no organization column.
    """

    __tablename__ = "evaluation_report_records"
    __table_args__ = (
        CheckConstraint(
            "task IN (" + ", ".join(f"'{task}'" for task in EVALUATION_TASKS) + ")",
            name="task_is_known",
        ),
        CheckConstraint("report_sha256 ~ '^[0-9a-f]{64}$'", name="report_sha256_is_hex"),
        Index("ix_evaluation_report_records_task", "task"),
        Index("ix_evaluation_report_records_model_provider", "model", "provider"),
        Index("ix_evaluation_report_records_dataset_fingerprint", "dataset_fingerprint"),
        Index("ix_evaluation_report_records_created_at", "created_at"),
        Index("uq_evaluation_report_records_report_sha256", "report_sha256", unique=True),
    )

    task: Mapped[str] = mapped_column(String(TASK_MAX_LENGTH))
    model: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    provider: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    dataset_name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH))
    dataset_fingerprint: Mapped[str] = mapped_column(String(FINGERPRINT_MAX_LENGTH))
    report_version: Mapped[int]
    report_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=EMPTY_JSON_OBJECT
    )
    report_sha256: Mapped[str] = mapped_column(String(SHA256_LENGTH))
    environment_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=EMPTY_JSON_OBJECT
    )
    # The system admin who imported it, kept as history if the account is gone.
    imported_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
