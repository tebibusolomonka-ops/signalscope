import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.domain.documents.chunk import EMPTY_JSON_OBJECT, TEXT_HASH_LENGTH
from signalscope.domain.entities.model import ENTITY_TYPE_MAX_LENGTH
from signalscope.domain.search.embedding_model import MODEL_MAX_LENGTH, PROVIDER_MAX_LENGTH

SURFACE_TEXT_MAX_LENGTH = 500


class EntityMention(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One place in a chunk where an extraction model found an entity.

    start_char and end_char point into DocumentChunk.text. Mentions are derived
    data, so they go away with their chunk. An entity cannot be deleted while
    mentions still point to it.
    """

    __tablename__ = "entity_mentions"
    __table_args__ = (
        # One model finds one entity at one place in a chunk at most once.
        UniqueConstraint("chunk_id", "start_char", "end_char", "provider", "model"),
        CheckConstraint("start_char >= 0", name="start_char_not_negative"),
        CheckConstraint("end_char > start_char", name="end_char_after_start_char"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_between_zero_and_one",
        ),
        CheckConstraint("chunk_text_hash ~ '^[0-9a-f]{64}$'", name="chunk_text_hash_is_hex"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_is_object"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="RESTRICT"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE")
    )
    # The text as it appears in the chunk, such as "Mrs Merkel".
    surface_text: Mapped[str] = mapped_column(String(SURFACE_TEXT_MAX_LENGTH))
    entity_type: Mapped[str] = mapped_column(String(ENTITY_TYPE_MAX_LENGTH))
    start_char: Mapped[int]
    end_char: Mapped[int]
    # How sure the model was, from 0 to 1, when it says.
    confidence: Mapped[float | None]
    # The model that found the mention.
    provider: Mapped[str] = mapped_column(String(PROVIDER_MAX_LENGTH))
    model: Mapped[str] = mapped_column(String(MODEL_MAX_LENGTH))
    # The chunk text the mention was found in. A different hash means the
    # chunk changed and the mention is out of date.
    chunk_text_hash: Mapped[str] = mapped_column(String(TEXT_HASH_LENGTH))
    # Anything else the model reports. "metadata" is taken on SQLAlchemy models.
    mention_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=EMPTY_JSON_OBJECT
    )
