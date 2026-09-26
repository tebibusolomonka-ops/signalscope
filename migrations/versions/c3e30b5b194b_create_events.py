"""Create events

Revision ID: c3e30b5b194b
Revises: 35358ee985d6
Create Date: 2026-09-27 00:08:09.191480

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3e30b5b194b"
down_revision: str | Sequence[str] | None = "35358ee985d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        )
        for name in ("created_at", "updated_at")
    ]


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.CheckConstraint("btrim(event_type) <> ''", name=op.f("ck_events_event_type_not_blank")),
        sa.CheckConstraint("btrim(title) <> ''", name=op.f("ck_events_title_not_blank")),
    )
    op.create_table(
        "event_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_evidence")),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_event_evidence_event_id_events"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.id"],
            name=op.f("fk_event_evidence_chunk_id_document_chunks"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "event_id",
            "chunk_id",
            "provider",
            "model",
            name=op.f("uq_event_evidence_event_id_chunk_id_provider_model"),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_event_evidence_confidence_between_zero_and_one"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'", name=op.f("ck_event_evidence_metadata_is_object")
        ),
    )
    op.create_index(
        op.f("ix_event_evidence_chunk_id"), "event_evidence", ["chunk_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_event_evidence_chunk_id"), table_name="event_evidence")
    op.drop_table("event_evidence")
    op.drop_table("events")
