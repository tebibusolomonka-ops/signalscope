"""Create document processing jobs

Revision ID: 2ebe321ade49
Revises: ed39cdaf19b6
Create Date: 2026-09-25 22:00:42.804229

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2ebe321ade49"
down_revision: str | Sequence[str] | None = "ed39cdaf19b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_processing_jobs")),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_processing_jobs_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["document_assets.id"],
            name=op.f("fk_document_processing_jobs_asset_id_document_assets"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("asset_id", name=op.f("uq_document_processing_jobs_asset_id")),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_document_processing_jobs_attempt_count_not_negative"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name=op.f("ck_document_processing_jobs_processing_job_status"),
        ),
    )
    op.create_index(
        op.f("ix_document_processing_jobs_document_id"),
        "document_processing_jobs",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_processing_jobs_status_available_at",
        "document_processing_jobs",
        ["status", "available_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_processing_jobs_status_available_at", table_name="document_processing_jobs"
    )
    op.drop_index(
        op.f("ix_document_processing_jobs_document_id"), table_name="document_processing_jobs"
    )
    op.drop_table("document_processing_jobs")
