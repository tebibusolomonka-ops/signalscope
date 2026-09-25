"""Create ingestion jobs

Revision ID: 6ade7c67bbe6
Revises: 5971c2b6a810
Create Date: 2026-09-25 13:54:46.272053

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6ade7c67bbe6"
down_revision: str | Sequence[str] | None = "5971c2b6a810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_jobs")),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_ingestion_jobs_source_id_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_ingestion_jobs_run_id_ingestion_runs"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("run_id", name=op.f("uq_ingestion_jobs_run_id")),
        sa.CheckConstraint(
            "attempt_count >= 0", name=op.f("ck_ingestion_jobs_attempt_count_not_negative")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name=op.f("ck_ingestion_jobs_ingestion_job_status"),
        ),
    )
    op.create_index(
        op.f("ix_ingestion_jobs_source_id"), "ingestion_jobs", ["source_id"], unique=False
    )
    op.create_index(
        "ix_ingestion_jobs_status_available_at",
        "ingestion_jobs",
        ["status", "available_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_jobs_status_available_at", table_name="ingestion_jobs")
    op.drop_index(op.f("ix_ingestion_jobs_source_id"), table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
