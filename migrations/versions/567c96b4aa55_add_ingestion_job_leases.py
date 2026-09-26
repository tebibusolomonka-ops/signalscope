"""Add ingestion job leases

Revision ID: 567c96b4aa55
Revises: dc4e91a00110
Create Date: 2026-09-26 13:35:39.451238

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "567c96b4aa55"
down_revision: str | Sequence[str] | None = "dc4e91a00110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


COLUMNS = ("heartbeat_at", "lease_expires_at")


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column(
            "ingestion_jobs", sa.Column(column, sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column("ingestion_jobs", column)
