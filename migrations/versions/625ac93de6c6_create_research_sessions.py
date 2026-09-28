"""Create research sessions

Revision ID: 625ac93de6c6
Revises: 97ebc65e728c
Create Date: 2026-09-28 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "625ac93de6c6"
down_revision: str | Sequence[str] | None = "97ebc65e728c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp(name: str) -> sa.Column[object]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "research_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("retrieval_mode", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_sessions")),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_research_sessions_source_id_sources"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "retrieval_mode IN ('lexical', 'semantic', 'hybrid', 'reranked')",
            name=op.f("ck_research_sessions_research_mode"),
        ),
    )
    op.create_index(
        op.f("ix_research_sessions_source_id"), "research_sessions", ["source_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_research_sessions_source_id"), table_name="research_sessions")
    op.drop_table("research_sessions")
