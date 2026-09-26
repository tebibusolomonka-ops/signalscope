"""Create document revisions

Revision ID: a657be153fd5
Revises: abde003661b7
Create Date: 2026-09-26 14:15:51.274345

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a657be153fd5"
down_revision: str | Sequence[str] | None = "abde003661b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=35), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_revisions")),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_revisions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_id", "version", name=op.f("uq_document_revisions_document_id_version")
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_document_revisions_version_positive")),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name=op.f("ck_document_revisions_metadata_is_object"),
        ),
    )


def downgrade() -> None:
    op.drop_table("document_revisions")
