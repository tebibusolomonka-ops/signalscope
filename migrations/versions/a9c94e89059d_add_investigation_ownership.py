"""Add investigation ownership

Revision ID: a9c94e89059d
Revises: f193df76c881
Create Date: 2026-09-29 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9c94e89059d"
down_revision: str | Sequence[str] | None = "f193df76c881"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing investigations keep NULL in both: they are legacy global records.
    op.add_column("investigations", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.add_column("investigations", sa.Column("created_by_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_investigations_organization_id_organizations"),
        "investigations",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_investigations_created_by_user_id_users"),
        "investigations",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_investigations_organization_id"),
        "investigations",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_investigations_organization_id"), table_name="investigations")
    op.drop_constraint(
        op.f("fk_investigations_created_by_user_id_users"), "investigations", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_investigations_organization_id_organizations"),
        "investigations",
        type_="foreignkey",
    )
    op.drop_column("investigations", "created_by_user_id")
    op.drop_column("investigations", "organization_id")
