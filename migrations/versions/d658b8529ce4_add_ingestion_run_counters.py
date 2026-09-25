"""Add ingestion run counters

Revision ID: d658b8529ce4
Revises: 0ee337bca33b
Create Date: 2026-09-25 12:16:06.079820

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d658b8529ce4"
down_revision: str | Sequence[str] | None = "0ee337bca33b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COUNTERS = ("items_seen", "documents_created", "duplicates_skipped")


def upgrade() -> None:
    for counter in COUNTERS:
        op.add_column(
            "ingestion_runs",
            sa.Column(counter, sa.Integer(), server_default=sa.text("0"), nullable=False),
        )
        op.create_check_constraint(
            op.f(f"ck_ingestion_runs_{counter}_not_negative"), "ingestion_runs", f"{counter} >= 0"
        )


def downgrade() -> None:
    for counter in reversed(COUNTERS):
        op.drop_constraint(
            op.f(f"ck_ingestion_runs_{counter}_not_negative"), "ingestion_runs", type_="check"
        )
        op.drop_column("ingestion_runs", counter)
