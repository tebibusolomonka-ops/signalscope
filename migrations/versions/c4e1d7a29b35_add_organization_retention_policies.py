"""Add organization retention policies

Revision ID: c4e1d7a29b35
Revises: a809b1740bcd
Create Date: 2026-10-01 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e1d7a29b35"
down_revision: str | Sequence[str] | None = "a809b1740bcd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "organization_retention_policies"


def upgrade() -> None:
    # No rows are added: without a policy, audit events are kept for ever.
    op.create_table(
        TABLE,
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("security_audit_days", sa.Integer(), nullable=True),
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
        sa.PrimaryKeyConstraint("organization_id", name=op.f("pk_organization_retention_policies")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_retention_policies_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "security_audit_days BETWEEN 30 AND 3650",
            name=op.f("ck_organization_retention_policies_security_audit_days_in_range"),
        ),
    )


def downgrade() -> None:
    op.drop_table(TABLE)
