import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.db.types import string_enum

ERROR_MESSAGE_MAX_LENGTH = 1000
COUNTERS = ("items_seen", "documents_created", "duplicates_skipped", "attempt_count")


class IngestionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestionRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One attempt to collect content from a source."""

    __tablename__ = "ingestion_runs"
    __table_args__ = tuple(
        CheckConstraint(f"{counter} >= 0", name=f"{counter}_not_negative") for counter in COUNTERS
    )

    # Restrict, so a source with ingestion history is never removed by accident.
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[IngestionStatus] = mapped_column(
        string_enum(IngestionStatus, name="ingestion_status"), default=IngestionStatus.PENDING
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A short message for people. Tracebacks belong in the logs.
    error_message: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_MAX_LENGTH))

    # Progress of the run so far, and its result once it has finished.
    items_seen: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    documents_created: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    duplicates_skipped: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    # How many times the run was executed. A new pending run has 0.
    attempt_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))


class IngestionJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestionJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A queued request for a worker to execute one ingestion run.

    The table is the queue. Workers claim jobs with SELECT ... FOR UPDATE SKIP LOCKED.
    """

    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="attempt_count_not_negative"),
        # Workers look for pending jobs that are available, oldest first.
        Index("ix_ingestion_jobs_status_available_at", "status", "available_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    # One job per run, so a run is never queued twice.
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="RESTRICT"), unique=True
    )
    status: Mapped[IngestionJobStatus] = mapped_column(
        string_enum(IngestionJobStatus, name="ingestion_job_status"),
        default=IngestionJobStatus.PENDING,
    )
    # A job cannot be claimed before this time.
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # How many times a worker claimed the job.
    attempt_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    # A short message for people. Tracebacks belong in the logs.
    last_error: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_MAX_LENGTH))
