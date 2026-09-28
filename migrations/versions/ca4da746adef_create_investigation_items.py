"""Create investigation items

Revision ID: ca4da746adef
Revises: e1e5729a02cb
Create Date: 2026-09-28 16:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ca4da746adef"
down_revision: str | Sequence[str] | None = "e1e5729a02cb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investigation_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("investigation_id", sa.Uuid(), nullable=False),
        sa.Column("item_type", sa.String(length=20), nullable=False),
        sa.Column("reference_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_investigation_items")),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
            name=op.f("fk_investigation_items_investigation_id_investigations"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "investigation_id",
            "item_type",
            "reference_id",
            name=op.f("uq_investigation_items_investigation_id_item_type_reference_id"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(snapshot) = 'object'",
            name=op.f("ck_investigation_items_snapshot_is_object"),
        ),
        sa.CheckConstraint(
            "item_type IN ('source', 'document', 'event', 'event_cluster', 'entity', 'claim', "
            "'research_session')",
            name=op.f("ck_investigation_items_investigation_item_type"),
        ),
    )


def downgrade() -> None:
    op.drop_table("investigation_items")
