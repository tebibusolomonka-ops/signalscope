"""Add research session organization

Revision ID: 8a83722f5691
Revises: 7ae71d53471b
Create Date: 2026-09-30 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8a83722f5691"
down_revision: str | Sequence[str] | None = "7ae71d53471b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing sessions keep NULL: they are legacy sessions.
    op.add_column("research_sessions", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_research_sessions_organization_id_organizations"),
        "research_sessions",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_research_sessions_organization_id"),
        "research_sessions",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_research_sessions_organization_id"), table_name="research_sessions")
    op.drop_constraint(
        op.f("fk_research_sessions_organization_id_organizations"),
        "research_sessions",
        type_="foreignkey",
    )
    op.drop_column("research_sessions", "organization_id")
