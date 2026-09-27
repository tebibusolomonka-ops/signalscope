"""Create event clusters

Revision ID: 97ebc65e728c
Revises: 89eb98878bd1
Create Date: 2026-09-27 09:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "97ebc65e728c"
down_revision: str | Sequence[str] | None = "89eb98878bd1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp(name: str) -> sa.Column[object]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "event_clusters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("canonical_title", sa.String(length=500), nullable=False),
        sa.Column("normalized_title", sa.String(length=500), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_clusters")),
        sa.CheckConstraint(
            "btrim(event_type) <> ''", name=op.f("ck_event_clusters_event_type_not_blank")
        ),
        sa.CheckConstraint(
            "btrim(canonical_title) <> ''",
            name=op.f("ck_event_clusters_canonical_title_not_blank"),
        ),
        sa.CheckConstraint(
            "btrim(normalized_title) <> ''",
            name=op.f("ck_event_clusters_normalized_title_not_blank"),
        ),
    )
    op.create_index(
        "ix_event_clusters_event_type_normalized_title",
        "event_clusters",
        ["event_type", "normalized_title"],
        unique=False,
    )
    op.create_table(
        "event_cluster_members",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("cluster_id", sa.Uuid(), nullable=False),
        timestamp("created_at"),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_event_cluster_members")),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_event_cluster_members_event_id_events"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["cluster_id"],
            ["event_clusters.id"],
            name=op.f("fk_event_cluster_members_cluster_id_event_clusters"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        op.f("ix_event_cluster_members_cluster_id"),
        "event_cluster_members",
        ["cluster_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_event_cluster_members_cluster_id"), table_name="event_cluster_members")
    op.drop_table("event_cluster_members")
    op.drop_index("ix_event_clusters_event_type_normalized_title", table_name="event_clusters")
    op.drop_table("event_clusters")
