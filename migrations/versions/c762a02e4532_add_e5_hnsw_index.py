"""Add E5 HNSW index

Revision ID: c762a02e4532
Revises: 66f2c6389d33
Create Date: 2026-09-26 20:13:20.751048

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c762a02e4532"
down_revision: str | Sequence[str] | None = "66f2c6389d33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_chunk_embeddings_e5_small_hnsw"


def upgrade() -> None:
    # Only rows of the E5 model are indexed, so no other vector is ever cast
    # to 384 dimensions. m and ef_construction keep the pgvector defaults.
    op.execute(
        f"""
        CREATE INDEX {INDEX_NAME} ON chunk_embeddings
        USING hnsw ((embedding::vector(384)) vector_cosine_ops)
        WHERE provider = 'sentence_transformers'
            AND model = 'intfloat/multilingual-e5-small'
            AND dimensions = 384
        """
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="chunk_embeddings")
