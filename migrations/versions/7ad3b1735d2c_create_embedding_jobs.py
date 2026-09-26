"""Create embedding jobs

Revision ID: 7ad3b1735d2c
Revises: f81e22d5f3d5
Create Date: 2026-09-26 18:37:15.746709

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7ad3b1735d2c"
down_revision: str | Sequence[str] | None = "f81e22d5f3d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "embedding_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embedding_jobs")),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.id"],
            name=op.f("fk_embedding_jobs_chunk_id_document_chunks"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "chunk_id", "provider", "model", name=op.f("uq_embedding_jobs_chunk_id_provider_model")
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name=op.f("ck_embedding_jobs_attempt_count_not_negative")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name=op.f("ck_embedding_jobs_embedding_job_status"),
        ),
    )
    op.create_index(
        "ix_embedding_jobs_status_available_at",
        "embedding_jobs",
        ["status", "available_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_embedding_jobs_status_available_at", table_name="embedding_jobs")
    op.drop_table("embedding_jobs")
