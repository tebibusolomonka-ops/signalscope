import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, and_, cast
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.domain.documents.chunk import TEXT_HASH_LENGTH
from signalscope.embeddings.models import MULTILINGUAL_E5_SMALL

PROVIDER_MAX_LENGTH = 50
MODEL_MAX_LENGTH = 100
E5_HNSW_INDEX_NAME = "ix_chunk_embeddings_e5_small_hnsw"


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


# An approximate nearest neighbour index for the local E5 model. The column
# has no fixed size, and HNSW needs one, so the index casts to 384 dimensions.
# The WHERE clause keeps every other model out of it, so their vectors are
# never cast. Other models can get their own partial index later.
Index(
    E5_HNSW_INDEX_NAME,
    cast(ChunkEmbedding.embedding, Vector(MULTILINGUAL_E5_SMALL.dimensions)).label("embedding"),
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
    postgresql_where=and_(
        ChunkEmbedding.provider == MULTILINGUAL_E5_SMALL.provider,
        ChunkEmbedding.model == MULTILINGUAL_E5_SMALL.model,
        ChunkEmbedding.dimensions == MULTILINGUAL_E5_SMALL.dimensions,
    ),
)
