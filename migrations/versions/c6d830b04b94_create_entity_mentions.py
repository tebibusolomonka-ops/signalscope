"""Create entity mentions

Revision ID: c6d830b04b94
Revises: 1f6ef0400631
Create Date: 2026-09-26 23:58:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c6d830b04b94"
down_revision: str | Sequence[str] | None = "1f6ef0400631"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entity_mentions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("surface_text", sa.String(length=500), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("chunk_text_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_mentions")),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_entity_mentions_entity_id_entities"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_entity_mentions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.id"],
            name=op.f("fk_entity_mentions_chunk_id_document_chunks"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "chunk_id",
            "start_char",
            "end_char",
            "provider",
            "model",
            name=op.f("uq_entity_mentions_chunk_id_start_char_end_char_provider_model"),
        ),
        sa.CheckConstraint(
            "start_char >= 0", name=op.f("ck_entity_mentions_start_char_not_negative")
        ),
        sa.CheckConstraint(
            "end_char > start_char", name=op.f("ck_entity_mentions_end_char_after_start_char")
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_entity_mentions_confidence_between_zero_and_one"),
        ),
        sa.CheckConstraint(
            "chunk_text_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_entity_mentions_chunk_text_hash_is_hex"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'", name=op.f("ck_entity_mentions_metadata_is_object")
        ),
    )
    op.create_index(
        op.f("ix_entity_mentions_entity_id"), "entity_mentions", ["entity_id"], unique=False
    )
    op.create_index(
        op.f("ix_entity_mentions_document_id"), "entity_mentions", ["document_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_entity_mentions_document_id"), table_name="entity_mentions")
    op.drop_index(op.f("ix_entity_mentions_entity_id"), table_name="entity_mentions")
    op.drop_table("entity_mentions")
