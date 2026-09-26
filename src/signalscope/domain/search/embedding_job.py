import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.core.errors import ERROR_MESSAGE_MAX_LENGTH
from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.db.types import string_enum
from signalscope.domain.search.embedding_model import MODEL_MAX_LENGTH, PROVIDER_MAX_LENGTH


class EmbeddingJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EmbeddingJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A queued request to embed one chunk with one provider and model.

    The table is the queue. Workers claim jobs with SELECT ... FOR UPDATE SKIP LOCKED.
    A chunk has at most one job per provider and model. When the chunk needs a
    new vector, the same job is put back in the queue.
    """

    __tablename__ = "embedding_jobs"
    __table_args__ = (
        UniqueConstraint("chunk_id", "provider", "model"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_not_negative"),
        # Workers look for pending jobs that are available, oldest first.
        Index("ix_embedding_jobs_status_available_at", "status", "available_at"),
    )

    # Jobs are derived from chunks, so they go away with their chunk.
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(PROVIDER_MAX_LENGTH))
    model: Mapped[str] = mapped_column(String(MODEL_MAX_LENGTH))
    status: Mapped[EmbeddingJobStatus] = mapped_column(
        string_enum(EmbeddingJobStatus, name="embedding_job_status"),
        default=EmbeddingJobStatus.PENDING,
    )
    # A job cannot be claimed before this time. New jobs are available right away.
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The last sign of life from the worker that holds the job.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A running job whose lease has run out can be put back in the queue.
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # How many times a worker claimed the job.
    attempt_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    # A short message for people. Tracebacks belong in the logs.
    last_error: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_MAX_LENGTH))
