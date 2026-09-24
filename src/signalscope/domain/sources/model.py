from enum import StrEnum

from sqlalchemy import Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

SOURCE_NAME_MAX_LENGTH = 200


class SourceType(StrEnum):
    WEB = "web"
    RSS = "rss"
    UPLOAD = "upload"
    API = "api"


class Source(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A place SignalScope gets content from, such as a feed or a website."""

    __tablename__ = "sources"

    # Stored as text with a check constraint instead of a PostgreSQL enum,
    # because new types are easier to add that way.
    type: Mapped[SourceType] = mapped_column(
        Enum(
            SourceType,
            name="source_type",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda types: [source_type.value for source_type in types],
        )
    )
    name: Mapped[str] = mapped_column(String(SOURCE_NAME_MAX_LENGTH))
    # Upload sources have no URL.
    url: Mapped[str | None] = mapped_column(Text)
