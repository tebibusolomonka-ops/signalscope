"""Create document chunks

Revision ID: 82bd0e6285b0
Revises: 2ebe321ade49
Create Date: 2026-09-25 22:18:24.265561

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "82bd0e6285b0"
down_revision: str | Sequence[str] | None = "2ebe321ade49"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks")),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_chunks_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_id", "position", name=op.f("uq_document_chunks_document_id_position")
        ),
        sa.CheckConstraint("position >= 0", name=op.f("ck_document_chunks_position_not_negative")),
        sa.CheckConstraint(
            "start_char >= 0", name=op.f("ck_document_chunks_start_char_not_negative")
        ),
        sa.CheckConstraint(
            "end_char >= start_char",
            name=op.f("ck_document_chunks_end_char_not_before_start_char"),
        ),
        sa.CheckConstraint("text <> ''", name=op.f("ck_document_chunks_text_not_empty")),
        sa.CheckConstraint(
            "text_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_document_chunks_text_hash_is_hex")
        ),
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
