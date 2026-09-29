"""Create security audit events

Revision ID: fb1d292a0ca2
Revises: 8c633fbceb79
Create Date: 2026-09-29 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fb1d292a0ca2"
down_revision: str | Sequence[str] | None = "8c633fbceb79"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "security_audit_events"
INDEXED = ("actor_user_id", "organization_id", "action", "created_at")


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column(
            "metadata",
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_audit_events")),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_security_audit_events_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_security_audit_events_organization_id_organizations"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "btrim(action) <> ''", name=op.f("ck_security_audit_events_action_not_blank")
        ),
        sa.CheckConstraint(
            "btrim(resource_type) <> ''",
            name=op.f("ck_security_audit_events_resource_type_not_blank"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name=op.f("ck_security_audit_events_metadata_is_object"),
        ),
    )
    for column in INDEXED:
        op.create_index(op.f(f"ix_{TABLE}_{column}"), TABLE, [column], unique=False)


def downgrade() -> None:
    for column in reversed(INDEXED):
        op.drop_index(op.f(f"ix_{TABLE}_{column}"), table_name=TABLE)
    op.drop_table(TABLE)
