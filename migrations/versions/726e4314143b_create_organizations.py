"""Create organizations

Revision ID: 726e4314143b
Revises: cdff2a983cd3
Create Date: 2026-09-29 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "726e4314143b"
down_revision: str | Sequence[str] | None = "cdff2a983cd3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp(name: str) -> sa.Column[object]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_organizations_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
        sa.CheckConstraint("btrim(name) <> ''", name=op.f("ck_organizations_name_not_blank")),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name=op.f("ck_organizations_slug_format")
        ),
    )


def downgrade() -> None:
    op.drop_table("organizations")
