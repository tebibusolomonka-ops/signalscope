"""Create organization disaster recovery drills

Revision ID: c7f1a2b3d4e5
Revises: b2d5f8a1c4e7
Create Date: 2026-10-05 08:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7f1a2b3d4e5"
down_revision: str | Sequence[str] | None = "b2d5f8a1c4e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "organization_disaster_recovery_drills"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("target_organization_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "mode",
            sa.Enum(
                "verification_only",
                "restore_test",
                name="disaster_recovery_drill_mode",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                name="disaster_recovery_drill_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("backup_export_id", sa.Uuid(), nullable=True),
        sa.Column("restore_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("safe_error", sa.String(length=1000), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_disaster_recovery_drills_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_organization_id"],
            ["organizations.id"],
            name=op.f(
                "fk_organization_disaster_recovery_drills_target_organization_id_organizations"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_organization_disaster_recovery_drills_requested_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["backup_export_id"],
            ["organization_exports.id"],
            name=op.f(
                "fk_organization_disaster_recovery_drills_backup_export_id_organization_exports"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["restore_id"],
            ["organization_restores.id"],
            name=op.f("fk_organization_disaster_recovery_drills_restore_id_organization_restores"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_disaster_recovery_drills")),
    )
    op.create_index(
        op.f("ix_organization_disaster_recovery_drills_requested_by_user_id"),
        TABLE,
        ["requested_by_user_id"],
    )
    op.create_index(
        "ix_organization_dr_drills_org_created_at",
        TABLE,
        ["organization_id", "created_at"],
    )
    op.create_index("ix_organization_dr_drills_status", TABLE, ["status"])


def downgrade() -> None:
    op.drop_index("ix_organization_dr_drills_status", table_name=TABLE)
    op.drop_index("ix_organization_dr_drills_org_created_at", table_name=TABLE)
    op.drop_index(
        op.f("ix_organization_disaster_recovery_drills_requested_by_user_id"), table_name=TABLE
    )
    op.drop_table(TABLE)
