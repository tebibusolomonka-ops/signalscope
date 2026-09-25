import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

TEXT_HASH_LENGTH = 64


class DocumentChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A piece of a document's text, used by search.

    Chunks are made from Document.content, so they are replaced as a whole,
    never edited one by one. start_char and end_char point into the content.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        # Its index also serves lookups by document_id, which comes first.
        UniqueConstraint("document_id", "position"),
        CheckConstraint("position >= 0", name="position_not_negative"),
        CheckConstraint("start_char >= 0", name="start_char_not_negative"),
        CheckConstraint("end_char >= start_char", name="end_char_not_before_start_char"),
        CheckConstraint("text <> ''", name="text_not_empty"),
        CheckConstraint("text_hash ~ '^[0-9a-f]{64}$'", name="text_hash_is_hex"),
    )

    # Chunks are derived data, so they go away with their document.
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    # Zero-based order of the chunk within the document.
    position: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    start_char: Mapped[int]
    end_char: Mapped[int]
    # Hex SHA-256 of the chunk text.
    text_hash: Mapped[str] = mapped_column(String(TEXT_HASH_LENGTH))
