"""Align operation attempt columns

Revision ID: d8f2c91a4e60
Revises: 921da3185dcc
Create Date: 2026-10-02 21:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8f2c91a4e60"
down_revision: str | Sequence[str] | None = "921da3185dcc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "operation_attempts"


def upgrade() -> None:
    op.alter_column(TABLE, "queue_name", type_=sa.String(length=20))
    op.alter_column(TABLE, "outcome", type_=sa.String(length=20))
    op.alter_column(TABLE, "safe_error", type_=sa.String(length=1000))


def downgrade() -> None:
    op.alter_column(TABLE, "safe_error", type_=sa.String(length=500))
    op.alter_column(TABLE, "outcome", type_=sa.String(length=9))
    op.alter_column(TABLE, "queue_name", type_=sa.String(length=10))
