import uuid
from typing import Any

# Importing the PostgreSQL dialect registers its versions of func.to_tsvector and
# the other search functions. Without it, whether the index below compiles
# would depend on which modules happened to be imported first.
import sqlalchemy.dialects.postgresql  # noqa: F401
from sqlalchemy import (
    CheckConstraint,
    ColumnElement,
    ForeignKey,
    Index,
    String,
    Text,
    TextClause,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

TEXT_HASH_LENGTH = 64
# Full text search uses the "simple" configuration, which lowercases words but
# does not assume a language.
TEXT_SEARCH_CONFIG = "simple"


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


def text_search_config() -> TextClause:
    # A constant, not a bound parameter, so PostgreSQL can match the index.
    return text(f"'{TEXT_SEARCH_CONFIG}'::regconfig")


def chunk_search_vector() -> ColumnElement[Any]:
    """The words of a chunk, as the full text search index stores them.

    Queries must use this same expression, or PostgreSQL does not use the index.
    """
    return func.to_tsvector(text_search_config(), DocumentChunk.text)


Index("ix_document_chunks_text_search", chunk_search_vector(), postgresql_using="gin")
