"""Add active operation guards

Revision ID: d8e2f4a6b1c3
Revises: c7f1a2b3d4e5
Create Date: 2026-10-05 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8e2f4a6b1c3"
down_revision: str | Sequence[str] | None = "c7f1a2b3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_organization_exports_active_organization",
        "organization_exports",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "uq_organization_restores_active_target",
        "organization_restores",
        ["target_organization_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('planned', 'running')"),
    )
    op.create_index(
        "uq_organization_dr_drills_active_restore_target",
        "organization_disaster_recovery_drills",
        ["target_organization_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'running' AND mode = 'restore_test' AND target_organization_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_organization_dr_drills_active_restore_target",
        table_name="organization_disaster_recovery_drills",
    )
    op.drop_index(
        "uq_organization_restores_active_target",
        table_name="organization_restores",
    )
    op.drop_index(
        "uq_organization_exports_active_organization",
        table_name="organization_exports",
    )
