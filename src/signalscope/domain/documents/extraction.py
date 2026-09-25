import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.domain.documents.asset import CONTENT_TYPE_MAX_LENGTH

PARSER_NAME_MAX_LENGTH = 100


class DocumentExtraction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """How the text of a document was last taken out of its raw file.

    The text itself is kept in Document.content, not here.
    """

    __tablename__ = "document_extractions"
    __table_args__ = (
        CheckConstraint("text_length >= 0", name="text_length_not_negative"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_is_object"),
    )

    # One record per document, replaced when the document is parsed again.
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), unique=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_assets.id", ondelete="RESTRICT"), index=True
    )
    parser_name: Mapped[str] = mapped_column(String(PARSER_NAME_MAX_LENGTH))
    content_type: Mapped[str] = mapped_column(String(CONTENT_TYPE_MAX_LENGTH))
    # What the parser reported, such as a page count. The attribute has another
    # name because SQLAlchemy uses "metadata" on every model.
    parser_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    text_length: Mapped[int]
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
