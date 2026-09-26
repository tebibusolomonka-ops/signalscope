import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.domain.documents.chunk import TEXT_HASH_LENGTH

PROVIDER_MAX_LENGTH = 50
MODEL_MAX_LENGTH = 100


class ChunkEmbedding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The vector of one chunk, made by one embedding model.

    A chunk can have one embedding per provider and model, so models can be
    compared and replaced. The column has no fixed size, because SignalScope
    has not settled on one model yet. Searches therefore have to filter by
    provider, model and dimensions before they compare vectors.
    """

    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id", "provider", "model"),
        CheckConstraint("dimensions > 0", name="dimensions_positive"),
        CheckConstraint("chunk_text_hash ~ '^[0-9a-f]{64}$'", name="chunk_text_hash_is_hex"),
    )

    # Embeddings are derived data, so they go away with their chunk.
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE")
    )
    # Who made the vector, such as "local", and with which model.
    provider: Mapped[str] = mapped_column(String(PROVIDER_MAX_LENGTH))
    model: Mapped[str] = mapped_column(String(MODEL_MAX_LENGTH))
    dimensions: Mapped[int]
    # The chunk text this vector was made from. A different hash means the
    # chunk changed and the vector is out of date.
    chunk_text_hash: Mapped[str] = mapped_column(String(TEXT_HASH_LENGTH))
    embedding: Mapped[list[float]] = mapped_column(Vector())
