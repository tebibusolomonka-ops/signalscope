import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.db.types import string_enum

ERROR_MESSAGE_MAX_LENGTH = 1000
COUNTERS = ("items_seen", "documents_created", "duplicates_skipped")


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
