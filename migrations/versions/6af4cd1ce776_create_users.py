"""Create users

Revision ID: 6af4cd1ce776
Revises: ca4da746adef
Create Date: 2026-09-29 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6af4cd1ce776"
down_revision: str | Sequence[str] | None = "ca4da746adef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp(name: str) -> sa.Column[object]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("normalized_email", sa.String(length=254), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_system_admin", sa.Boolean(), server_default=sa.false(), nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("normalized_email", name=op.f("uq_users_normalized_email")),
        sa.CheckConstraint("btrim(email) <> ''", name=op.f("ck_users_email_not_blank")),
        sa.CheckConstraint(
            "btrim(display_name) <> ''", name=op.f("ck_users_display_name_not_blank")
        ),
    )


def downgrade() -> None:
    op.drop_table("users")
