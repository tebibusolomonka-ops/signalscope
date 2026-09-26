"""Create claim extraction jobs

Revision ID: 89eb98878bd1
Revises: e6554a64a987
Create Date: 2026-09-27 00:47:39.976807

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "89eb98878bd1"
down_revision: str | Sequence[str] | None = "e6554a64a987"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "claim_extraction_jobs",
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
        sa.Column("lease_token", sa.Uuid(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_extraction_jobs")),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.id"],
            name=op.f("fk_claim_extraction_jobs_chunk_id_document_chunks"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "chunk_id",
            "provider",
            "model",
            name=op.f("uq_claim_extraction_jobs_chunk_id_provider_model"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_claim_extraction_jobs_attempt_count_not_negative"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name=op.f("ck_claim_extraction_jobs_claim_extraction_job_status"),
        ),
    )
    op.create_index(
        "ix_claim_extraction_jobs_status_available_at",
        "claim_extraction_jobs",
        ["status", "available_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_claim_extraction_jobs_status_available_at", table_name="claim_extraction_jobs"
    )
    op.drop_table("claim_extraction_jobs")
