from enum import StrEnum

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.db.types import string_enum

SOURCE_NAME_MAX_LENGTH = 200


class SourceType(StrEnum):
    WEB = "web"
    RSS = "rss"
    UPLOAD = "upload"
    API = "api"


class Source(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A place SignalScope gets content from, such as a feed or a website."""

    __tablename__ = "sources"

    type: Mapped[SourceType] = mapped_column(string_enum(SourceType, name="source_type"))
    name: Mapped[str] = mapped_column(String(SOURCE_NAME_MAX_LENGTH))
    # Upload sources have no URL.
    url: Mapped[str | None] = mapped_column(Text)
