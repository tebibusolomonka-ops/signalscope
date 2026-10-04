"""Add evaluation report records

Revision ID: d5b2f3c6a7e1
Revises: e4a7c8d91f20
Create Date: 2026-10-04 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5b2f3c6a7e1"
down_revision: str | Sequence[str] | None = "e4a7c8d91f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "evaluation_report_records"
TASKS = (
    "embedding_retrieval",
    "reranking",
    "structured_extraction",
    "answer_citation",
    "relation_evaluation",
)


def upgrade() -> None:
    task_values = ", ".join(f"'{task}'" for task in TASKS)
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=200), nullable=False),
        sa.Column("dataset_name", sa.String(length=200), nullable=False),
        sa.Column("dataset_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("report_version", sa.Integer(), nullable=False),
        sa.Column(
            "report_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("report_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "environment_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("imported_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_report_records")),
        sa.ForeignKeyConstraint(
            ["imported_by_user_id"],
            ["users.id"],
            name=op.f("fk_evaluation_report_records_imported_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            f"task IN ({task_values})",
            name=op.f("ck_evaluation_report_records_task_is_known"),
        ),
        sa.CheckConstraint(
            "report_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_evaluation_report_records_report_sha256_is_hex"),
        ),
    )
    op.create_index(op.f("ix_evaluation_report_records_task"), TABLE, ["task"])
    op.create_index(
        op.f("ix_evaluation_report_records_model_provider"), TABLE, ["model", "provider"]
    )
    op.create_index(
        op.f("ix_evaluation_report_records_dataset_fingerprint"), TABLE, ["dataset_fingerprint"]
    )
    op.create_index(op.f("ix_evaluation_report_records_created_at"), TABLE, ["created_at"])
    op.create_index(
        op.f("uq_evaluation_report_records_report_sha256"),
        TABLE,
        ["report_sha256"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table(TABLE)
