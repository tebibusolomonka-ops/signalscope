"""Create document assets

Revision ID: 68c211521c5a
Revises: 6ade7c67bbe6
Create Date: 2026-09-25 21:49:34.612906

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "68c211521c5a"
down_revision: str | Sequence[str] | None = "6ade7c67bbe6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_assets")),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_assets_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("document_id", name=op.f("uq_document_assets_document_id")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_document_assets_storage_key")),
        sa.CheckConstraint(
            "size_bytes >= 0", name=op.f("ck_document_assets_size_bytes_not_negative")
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_document_assets_sha256_is_hex")
        ),
    )


def downgrade() -> None:
    op.drop_table("document_assets")
