"""Create document extractions

Revision ID: ed39cdaf19b6
Revises: 68c211521c5a
Create Date: 2026-09-25 21:56:42.372778

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ed39cdaf19b6"
down_revision: str | Sequence[str] | None = "68c211521c5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_extractions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("parser_name", sa.String(length=100), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("text_length", sa.Integer(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_extractions")),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_extractions_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["document_assets.id"],
            name=op.f("fk_document_extractions_asset_id_document_assets"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("document_id", name=op.f("uq_document_extractions_document_id")),
        sa.CheckConstraint(
            "text_length >= 0", name=op.f("ck_document_extractions_text_length_not_negative")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name=op.f("ck_document_extractions_metadata_is_object"),
        ),
    )
    op.create_index(
        op.f("ix_document_extractions_asset_id"),
        "document_extractions",
        ["asset_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_document_extractions_asset_id"), table_name="document_extractions")
    op.drop_table("document_extractions")
