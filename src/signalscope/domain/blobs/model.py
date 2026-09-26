from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.core.errors import ERROR_MESSAGE_MAX_LENGTH
from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.domain.documents.asset import STORAGE_KEY_MAX_LENGTH


class BlobCleanupTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A stored file that should be deleted, because nothing points to it anymore.

    A row exists only while the cleanup is still to be done.
    """

    __tablename__ = "blob_cleanup_tasks"
    __table_args__ = (CheckConstraint("attempt_count >= 0", name="attempt_count_not_negative"),)

    # Only the key in the blob store, never a file system path.
    storage_key: Mapped[str] = mapped_column(String(STORAGE_KEY_MAX_LENGTH), unique=True)
    attempt_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    # The cleanup is not tried again before this time.
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # A short message for people. Tracebacks belong in the logs.
    last_error: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_MAX_LENGTH))
