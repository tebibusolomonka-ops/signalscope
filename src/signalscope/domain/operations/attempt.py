import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.core.errors import ERROR_MESSAGE_MAX_LENGTH
from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.db.types import string_enum


class OperationAttemptQueue(StrEnum):
    INGESTION = "ingestion"
    PROCESSING = "processing"
    EMBEDDING = "embedding"
    ENTITY = "entity"
    EVENT = "event"
    CLAIM = "claim"


class OperationAttemptOutcome(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RECOVERED = "recovered"


class OperationAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One durable record of a worker claiming and finishing a queued job."""

    __tablename__ = "operation_attempts"
    __table_args__ = (
        CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        Index("ix_operation_attempts_organization_created_at", "organization_id", "created_at"),
        Index("ix_operation_attempts_resource", "resource_type", "resource_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    queue_name: Mapped[OperationAttemptQueue] = mapped_column(
        string_enum(OperationAttemptQueue, name="operation_attempt_queue"), index=True
    )
    # Deliberately not a foreign key: history outlives queue rows.
    job_id: Mapped[uuid.UUID] = mapped_column(index=True)
    attempt_number: Mapped[int]
    resource_type: Mapped[str] = mapped_column(String(32))
    # Deliberately not a foreign key: content may be removed before its history.
    resource_id: Mapped[uuid.UUID | None]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[OperationAttemptOutcome] = mapped_column(
        string_enum(OperationAttemptOutcome, name="operation_attempt_outcome"),
        default=OperationAttemptOutcome.RUNNING,
    )
    safe_error: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_MAX_LENGTH))
