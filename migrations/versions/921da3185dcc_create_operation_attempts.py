"""Create operation attempts

Revision ID: 921da3185dcc
Revises: c4e1d7a29b35
Create Date: 2026-10-02 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "921da3185dcc"
down_revision: str | Sequence[str] | None = "c4e1d7a29b35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "operation_attempts"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "queue_name",
            sa.Enum(
                "ingestion",
                "processing",
                "embedding",
                "entity",
                "event",
                "claim",
                name="operation_attempt_queue",
                native_enum=False,
                length=10,
            ),
            nullable=False,
        ),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum(
                "running",
                "succeeded",
                "failed",
                "recovered",
                name="operation_attempt_outcome",
                native_enum=False,
                length=9,
            ),
            nullable=False,
        ),
        sa.Column("safe_error", sa.String(length=500), nullable=True),
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
        sa.CheckConstraint(
            "attempt_number > 0", name=op.f("ck_operation_attempts_attempt_number_positive")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_operation_attempts_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operation_attempts")),
    )
    op.create_index("ix_operation_attempts_job_id", TABLE, ["job_id"])
    op.create_index("ix_operation_attempts_queue_name", TABLE, ["queue_name"])
    op.create_index(
        "ix_operation_attempts_organization_created_at", TABLE, ["organization_id", "created_at"]
    )
    op.create_index("ix_operation_attempts_resource", TABLE, ["resource_type", "resource_id"])


def downgrade() -> None:
    op.drop_index("ix_operation_attempts_resource", table_name=TABLE)
    op.drop_index("ix_operation_attempts_organization_created_at", table_name=TABLE)
    op.drop_index("ix_operation_attempts_queue_name", table_name=TABLE)
    op.drop_index("ix_operation_attempts_job_id", table_name=TABLE)
    op.drop_table(TABLE)
