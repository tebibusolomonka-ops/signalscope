"""Create investigation collaborators

Revision ID: 8c633fbceb79
Revises: a9c94e89059d
Create Date: 2026-09-29 15:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8c633fbceb79"
down_revision: str | Sequence[str] | None = "a9c94e89059d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp(name: str) -> sa.Column[object]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "investigation_collaborators",
        sa.Column("investigation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.PrimaryKeyConstraint(
            "investigation_id", "user_id", name=op.f("pk_investigation_collaborators")
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
            name=op.f("fk_investigation_collaborators_investigation_id_investigations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_investigation_collaborators_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'editor', 'viewer')",
            name=op.f("ck_investigation_collaborators_collaborator_role"),
        ),
    )
    op.create_index(
        op.f("ix_investigation_collaborators_user_id"),
        "investigation_collaborators",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_investigation_collaborators_user_id"), table_name="investigation_collaborators"
    )
    op.drop_table("investigation_collaborators")
