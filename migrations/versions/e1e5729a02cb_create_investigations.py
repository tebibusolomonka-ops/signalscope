"""Create investigations

Revision ID: e1e5729a02cb
Revises: 09376fcf43b6
Create Date: 2026-09-28 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1e5729a02cb"
down_revision: str | Sequence[str] | None = "09376fcf43b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp(name: str) -> sa.Column[object]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "investigations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_investigations")),
        sa.CheckConstraint("btrim(title) <> ''", name=op.f("ck_investigations_title_not_blank")),
        sa.CheckConstraint(
            "status IN ('open', 'closed')", name=op.f("ck_investigations_investigation_status")
        ),
    )


def downgrade() -> None:
    op.drop_table("investigations")
