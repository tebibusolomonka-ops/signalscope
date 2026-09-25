"""Add source scheduling fields

Revision ID: 5971c2b6a810
Revises: fa2fa72c8a38
Create Date: 2026-09-25 13:47:10.596746

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5971c2b6a810"
down_revision: str | Sequence[str] | None = "fa2fa72c8a38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("ingestion_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("sources", sa.Column("ingestion_interval_minutes", sa.Integer(), nullable=True))
    op.add_column(
        "sources", sa.Column("next_ingestion_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_sources_ingestion_interval_minutes_in_range"),
        "sources",
        "ingestion_interval_minutes BETWEEN 1 AND 10080",
    )
    op.create_check_constraint(
        op.f("ck_sources_enabled_ingestion_has_interval"),
        "sources",
        "NOT ingestion_enabled OR ingestion_interval_minutes IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_sources_enabled_ingestion_has_interval"), "sources", type_="check")
    op.drop_constraint(
        op.f("ck_sources_ingestion_interval_minutes_in_range"), "sources", type_="check"
    )
    op.drop_column("sources", "next_ingestion_at")
    op.drop_column("sources", "ingestion_interval_minutes")
    op.drop_column("sources", "ingestion_enabled")
