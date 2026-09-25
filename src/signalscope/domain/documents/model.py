import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.domain.sources.model import Source

EXTERNAL_ID_MAX_LENGTH = 500
URL_MAX_LENGTH = 2048
LANGUAGE_MAX_LENGTH = 35


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One content item collected from a source, such as an article or a PDF."""

    __tablename__ = "documents"
    __table_args__ = (
        # One source should not store the same item twice. This index also covers
        # lookups by source_id.
        UniqueConstraint("source_id", "external_id"),
        # Duplicate checks during ingestion look documents up by source and URL.
        Index("ix_documents_source_id_url", "source_id", "url"),
    )

    # Restrict, so deleting a source never removes its documents by accident.
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"))
    # The ID the source uses for this item, such as a feed GUID.
    external_id: Mapped[str | None] = mapped_column(String(EXTERNAL_ID_MAX_LENGTH))
    # Where the item itself lives, such as the article link in a feed entry.
    url: Mapped[str | None] = mapped_column(String(URL_MAX_LENGTH))
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    # BCP 47 language tag, such as "en" or "pt-BR".
    language: Mapped[str | None] = mapped_column(String(LANGUAGE_MAX_LENGTH))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Async sessions cannot lazy load, so the source has to be loaded on purpose.
    source: Mapped[Source] = relationship(lazy="raise")
