import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.core.errors import ERROR_MESSAGE_MAX_LENGTH
from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.db.types import string_enum


class ProcessingJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentProcessingJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A queued request to parse the raw file of a document.

    The table is the queue. Workers claim jobs with SELECT ... FOR UPDATE SKIP LOCKED.
    """

    __tablename__ = "document_processing_jobs"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="attempt_count_not_negative"),
        # Workers look for pending jobs that are available, oldest first.
        Index("ix_document_processing_jobs_status_available_at", "status", "available_at"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    # One job per asset, so the same file is never queued twice.
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_assets.id", ondelete="RESTRICT"), unique=True
    )
    status: Mapped[ProcessingJobStatus] = mapped_column(
        string_enum(ProcessingJobStatus, name="processing_job_status"),
        default=ProcessingJobStatus.PENDING,
    )
    # A job cannot be claimed before this time. New jobs are available right away.
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # How many times a worker claimed the job.
    attempt_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    # A short message for people. Tracebacks belong in the logs.
    last_error: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_MAX_LENGTH))
