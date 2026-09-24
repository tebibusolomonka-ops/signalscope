"""Create ingestion runs

Revision ID: 8eeb5be26820
Revises: 482795860943
Create Date: 2026-09-24 13:05:29.354897

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8eeb5be26820"
down_revision: str | Sequence[str] | None = "482795860943"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_runs")),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_ingestion_runs_source_id_sources"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name=op.f("ck_ingestion_runs_ingestion_status"),
        ),
    )
    op.create_index(
        op.f("ix_ingestion_runs_source_id"), "ingestion_runs", ["source_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ingestion_runs_source_id"), table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
