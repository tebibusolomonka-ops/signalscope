"""Enforce organization backup frequency

Revision ID: a1c4e7b9d2f5
Revises: f6a8b1c2d3e4
Create Date: 2026-10-04 23:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1c4e7b9d2f5"
down_revision: str | Sequence[str] | None = "f6a8b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "organization_backup_policies"
CONSTRAINT = "ck_organization_backup_policies_organization_backup_frequency"


def upgrade() -> None:
    op.create_check_constraint(CONSTRAINT, TABLE, "frequency IN ('daily', 'weekly')")


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
