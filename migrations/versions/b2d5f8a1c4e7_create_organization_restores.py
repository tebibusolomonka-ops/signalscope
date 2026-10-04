"""Create organization restores

Revision ID: b2d5f8a1c4e7
Revises: a1c4e7b9d2f5
Create Date: 2026-10-04 23:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2d5f8a1c4e7"
down_revision: str | Sequence[str] | None = "a1c4e7b9d2f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "organization_restores"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_organization_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("source_export_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "planned",
                "running",
                "completed",
                "failed",
                name="organization_restore_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "source_export_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_organization_restores_source_export_sha256_is_hex"),
        ),
        sa.ForeignKeyConstraint(
            ["target_organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_restores_target_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_organization_restores_requested_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_restores")),
    )
    op.create_index(
        "ix_organization_restores_requested_by_user_id", TABLE, ["requested_by_user_id"]
    )
    op.create_index(
        "ix_organization_restores_target_created_at",
        TABLE,
        ["target_organization_id", "created_at"],
    )
    op.create_index("ix_organization_restores_status", TABLE, ["status"])


def downgrade() -> None:
    op.drop_index("ix_organization_restores_status", table_name=TABLE)
    op.drop_index("ix_organization_restores_target_created_at", table_name=TABLE)
    op.drop_index("ix_organization_restores_requested_by_user_id", table_name=TABLE)
    op.drop_table(TABLE)
