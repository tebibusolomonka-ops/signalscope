"""Create user password credentials

Revision ID: 2e7486808caa
Revises: 6af4cd1ce776
Create Date: 2026-09-29 09:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2e7486808caa"
down_revision: str | Sequence[str] | None = "6af4cd1ce776"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp(name: str) -> sa.Column[object]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "user_password_credentials",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        timestamp("password_changed_at"),
        timestamp("created_at"),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_password_credentials")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_password_credentials_user_id_users"),
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("user_password_credentials")
