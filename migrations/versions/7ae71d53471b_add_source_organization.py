"""Add source organization

Revision ID: 7ae71d53471b
Revises: 23438041f111
Create Date: 2026-09-30 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7ae71d53471b"
down_revision: str | Sequence[str] | None = "23438041f111"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing sources keep NULL: they are legacy content, not assigned to anyone.
    op.add_column("sources", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_sources_organization_id_organizations"),
        "sources",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_sources_organization_id"), "sources", ["organization_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_sources_organization_id"), table_name="sources")
    op.drop_constraint(
        op.f("fk_sources_organization_id_organizations"), "sources", type_="foreignkey"
    )
    op.drop_column("sources", "organization_id")
