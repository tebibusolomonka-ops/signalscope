"""Create chunk embeddings

Revision ID: f81e22d5f3d5
Revises: 360eb1ac9b23
Create Date: 2026-09-26 15:11:09.643512

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "f81e22d5f3d5"
down_revision: str | Sequence[str] | None = "360eb1ac9b23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("chunk_text_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunk_embeddings")),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.id"],
            name=op.f("fk_chunk_embeddings_chunk_id_document_chunks"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "chunk_id",
            "provider",
            "model",
            name=op.f("uq_chunk_embeddings_chunk_id_provider_model"),
        ),
        sa.CheckConstraint("dimensions > 0", name=op.f("ck_chunk_embeddings_dimensions_positive")),
        sa.CheckConstraint(
            "chunk_text_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_chunk_embeddings_chunk_text_hash_is_hex"),
        ),
    )


def downgrade() -> None:
    op.drop_table("chunk_embeddings")
