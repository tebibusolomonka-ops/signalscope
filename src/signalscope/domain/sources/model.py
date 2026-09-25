from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.db.types import string_enum

SOURCE_NAME_MAX_LENGTH = 200
# One week. Sources that change less often can be ingested by hand.
MAX_INGESTION_INTERVAL_MINUTES = 7 * 24 * 60


class SourceType(StrEnum):
    WEB = "web"
    RSS = "rss"
    UPLOAD = "upload"
    API = "api"


class Source(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A place SignalScope gets content from, such as a feed or a website."""

    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(
            f"ingestion_interval_minutes BETWEEN 1 AND {MAX_INGESTION_INTERVAL_MINUTES}",
            name="ingestion_interval_minutes_in_range",
        ),
        # The scheduler needs the interval to work out the next time.
        CheckConstraint(
            "NOT ingestion_enabled OR ingestion_interval_minutes IS NOT NULL",
            name="enabled_ingestion_has_interval",
        ),
    )

    type: Mapped[SourceType] = mapped_column(string_enum(SourceType, name="source_type"))
    name: Mapped[str] = mapped_column(String(SOURCE_NAME_MAX_LENGTH))
    # Upload sources have no URL.
    url: Mapped[str | None] = mapped_column(Text)
    # Scheduled ingestion. A source is ingested when it is enabled and
    # next_ingestion_at has passed.
    ingestion_enabled: Mapped[bool] = mapped_column(default=False, server_default=false())
    ingestion_interval_minutes: Mapped[int | None]
    next_ingestion_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
