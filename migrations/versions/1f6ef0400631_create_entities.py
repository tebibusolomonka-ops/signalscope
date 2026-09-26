"""Create entities

Revision ID: 1f6ef0400631
Revises: c762a02e4532
Create Date: 2026-09-26 23:54:18.759161

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1f6ef0400631"
down_revision: str | Sequence[str] | None = "c762a02e4532"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canonical_name", sa.String(length=300), nullable=False),
        sa.Column("normalized_name", sa.String(length=300), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entities")),
        sa.UniqueConstraint(
            "normalized_name",
            "entity_type",
            name=op.f("uq_entities_normalized_name_entity_type"),
        ),
        sa.CheckConstraint(
            "btrim(canonical_name) <> ''", name=op.f("ck_entities_canonical_name_not_blank")
        ),
        sa.CheckConstraint(
            "btrim(normalized_name) <> ''", name=op.f("ck_entities_normalized_name_not_blank")
        ),
        sa.CheckConstraint(
            "btrim(entity_type) <> ''", name=op.f("ck_entities_entity_type_not_blank")
        ),
    )


def downgrade() -> None:
    op.drop_table("entities")
