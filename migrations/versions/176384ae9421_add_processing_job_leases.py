"""Add processing job leases

Revision ID: 176384ae9421
Revises: 567c96b4aa55
Create Date: 2026-09-26 13:41:58.487854

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "176384ae9421"
down_revision: str | Sequence[str] | None = "567c96b4aa55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


COLUMNS = ("heartbeat_at", "lease_expires_at")


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column(
            "document_processing_jobs",
            sa.Column(column, sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column("document_processing_jobs", column)
