"""Create research turns

Revision ID: 09376fcf43b6
Revises: 625ac93de6c6
Create Date: 2026-09-28 13:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "09376fcf43b6"
down_revision: str | Sequence[str] | None = "625ac93de6c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def json_array(name: str) -> sa.Column[object]:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'[]'::jsonb"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "research_turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        json_array("citation_ids"),
        json_array("evidence_snapshot"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_turns")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["research_sessions.id"],
            name=op.f("fk_research_turns_session_id_research_sessions"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "session_id", "sequence", name=op.f("uq_research_turns_session_id_sequence")
        ),
        sa.CheckConstraint("sequence > 0", name=op.f("ck_research_turns_sequence_positive")),
        sa.CheckConstraint(
            "btrim(question) <> ''", name=op.f("ck_research_turns_question_not_blank")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(citation_ids) = 'array'",
            name=op.f("ck_research_turns_citation_ids_is_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_snapshot) = 'array'",
            name=op.f("ck_research_turns_evidence_snapshot_is_array"),
        ),
    )


def downgrade() -> None:
    op.drop_table("research_turns")
