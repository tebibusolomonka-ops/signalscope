import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import LAST, UUIDPrimaryKeyMixin
from signalscope.domain.documents.model import (
    CONTENT_HASH_LENGTH,
    LANGUAGE_MAX_LENGTH,
    URL_MAX_LENGTH,
)


class DocumentRevision(UUIDPrimaryKeyMixin, Base):
    """An earlier processed state of a document, kept when it was replaced.

    Revisions are history, so they are never changed after they are written.
    The raw file is not copied. Only its extracted text and metadata are kept.
    """

    __tablename__ = "document_revisions"
    __table_args__ = (
        # Its index also serves lookups by document_id, which comes first.
        UniqueConstraint("document_id", "version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_is_object"),
    )
    # Read created_at back after INSERT, as async sessions cannot load it later.
    __mapper_args__: dict[str, Any] = {"eager_defaults": True}

    # History goes away with its document.
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    # 1 for the oldest kept state of a document, then counting up.
    version: Mapped[int]
    title: Mapped[str | None] = mapped_column(Text)
    # Empty for a document that was never processed before.
    content: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(LANGUAGE_MAX_LENGTH))
    url: Mapped[str | None] = mapped_column(String(URL_MAX_LENGTH))
    content_hash: Mapped[str | None] = mapped_column(String(CONTENT_HASH_LENGTH))
    # The extraction metadata at that time. SQLAlchemy uses "metadata" on every
    # model, so the attribute has another name.
    parser_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), sort_order=LAST
    )
