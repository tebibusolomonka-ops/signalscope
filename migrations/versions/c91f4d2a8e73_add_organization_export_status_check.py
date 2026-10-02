"""Add organization export status check

Revision ID: c91f4d2a8e73
Revises: b7e4c6a91d02
Create Date: 2026-10-02 22:40:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c91f4d2a8e73"
down_revision: str | Sequence[str] | None = "b7e4c6a91d02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "organization_exports"
CONSTRAINT = "ck_organization_exports_organization_export_status"


def upgrade() -> None:
    op.create_check_constraint(
        CONSTRAINT,
        TABLE,
        "status IN ('pending', 'running', 'completed', 'failed', 'expired')",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
