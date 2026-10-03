"""Create authentication throttles

Revision ID: e4a7c8d91f20
Revises: c91f4d2a8e73
Create Date: 2026-10-03 20:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4a7c8d91f20"
down_revision: str | Sequence[str] | None = "c91f4d2a8e73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "authentication_throttles"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("identifier", sa.String(length=64), nullable=False),
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "identifier ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_authentication_throttles_identifier_is_sha256_hex"),
        ),
        sa.CheckConstraint(
            "failure_count >= 0",
            name=op.f("ck_authentication_throttles_failure_count_not_negative"),
        ),
        sa.PrimaryKeyConstraint("identifier", name=op.f("pk_authentication_throttles")),
    )
    op.create_index(op.f("ix_authentication_throttles_blocked_until"), TABLE, ["blocked_until"])
    op.create_index(op.f("ix_authentication_throttles_updated_at"), TABLE, ["updated_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_authentication_throttles_updated_at"), table_name=TABLE)
    op.drop_index(op.f("ix_authentication_throttles_blocked_until"), table_name=TABLE)
    op.drop_table(TABLE)
