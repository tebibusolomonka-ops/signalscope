"""Add ingestion run attempt count

Revision ID: fa2fa72c8a38
Revises: d658b8529ce4
Create Date: 2026-09-25 13:38:39.519721

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fa2fa72c8a38"
down_revision: str | Sequence[str] | None = "d658b8529ce4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingestion_runs",
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_ingestion_runs_attempt_count_not_negative"),
        "ingestion_runs",
        "attempt_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_ingestion_runs_attempt_count_not_negative"), "ingestion_runs", type_="check"
    )
    op.drop_column("ingestion_runs", "attempt_count")
