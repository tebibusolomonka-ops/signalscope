"""Create organization backup policies

Revision ID: f6a8b1c2d3e4
Revises: d5b2f3c6a7e1
Create Date: 2026-10-04 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a8b1c2d3e4"
down_revision: str | Sequence[str] | None = "d5b2f3c6a7e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "organization_backup_policies"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "frequency",
            sa.Enum(
                "daily",
                "weekly",
                name="organization_backup_frequency",
                native_enum=False,
                length=20,
            ),
            server_default="daily",
            nullable=False,
        ),
        sa.Column("retention_count", sa.Integer(), server_default="7", nullable=False),
        sa.Column("include_assets", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "retention_count BETWEEN 1 AND 100",
            name=op.f("ck_organization_backup_policies_retention_count_in_range"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_backup_policies_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", name=op.f("pk_organization_backup_policies")),
    )


def downgrade() -> None:
    op.drop_table(TABLE)
