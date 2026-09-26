"""Create blob cleanup tasks

Revision ID: abde003661b7
Revises: 176384ae9421
Create Date: 2026-09-26 14:08:04.175189

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "abde003661b7"
down_revision: str | Sequence[str] | None = "176384ae9421"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "blob_cleanup_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blob_cleanup_tasks")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_blob_cleanup_tasks_storage_key")),
        sa.CheckConstraint(
            "attempt_count >= 0", name=op.f("ck_blob_cleanup_tasks_attempt_count_not_negative")
        ),
    )


def downgrade() -> None:
    op.drop_table("blob_cleanup_tasks")
