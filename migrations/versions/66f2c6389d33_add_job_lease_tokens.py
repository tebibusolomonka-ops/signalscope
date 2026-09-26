"""Add job lease tokens

Revision ID: 66f2c6389d33
Revises: 7ad3b1735d2c
Create Date: 2026-09-26 19:47:36.057334

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "66f2c6389d33"
down_revision: str | Sequence[str] | None = "7ad3b1735d2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Running jobs from before this revision keep a NULL token. They are recovered
# once their lease runs out, like any job whose worker is gone.
TABLES = ("ingestion_jobs", "document_processing_jobs", "embedding_jobs")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("lease_token", sa.Uuid(), nullable=True))


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_column(table, "lease_token")
