"""Create organization exports

Revision ID: b7e4c6a91d02
Revises: d8f2c91a4e60
Create Date: 2026-10-02 21:35:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e4c6a91d02"
down_revision: str | Sequence[str] | None = "d8f2c91a4e60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "organization_exports"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                "expired",
                name="organization_export_status",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("format_version", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("artifact_key", sa.String(length=500), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
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
            "size_bytes IS NULL OR size_bytes >= 0",
            name=op.f("ck_organization_exports_size_bytes_not_negative"),
        ),
        sa.CheckConstraint(
            "sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_organization_exports_sha256_is_hex"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_exports_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_organization_exports_requested_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_exports")),
    )
    op.create_index("ix_organization_exports_requested_by_user_id", TABLE, ["requested_by_user_id"])
    op.create_index(
        "ix_organization_exports_organization_created_at", TABLE, ["organization_id", "created_at"]
    )
    op.create_index("ix_organization_exports_status_expires_at", TABLE, ["status", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_organization_exports_status_expires_at", table_name=TABLE)
    op.drop_index("ix_organization_exports_organization_created_at", table_name=TABLE)
    op.drop_index("ix_organization_exports_requested_by_user_id", table_name=TABLE)
    op.drop_table(TABLE)
