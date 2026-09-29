"""Create organization invitations

Revision ID: 23438041f111
Revises: fb1d292a0ca2
Create Date: 2026-09-29 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "23438041f111"
down_revision: str | Sequence[str] | None = "fb1d292a0ca2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "organization_invitations"
INDEXED = ("organization_id", "normalized_email", "expires_at")


def timestamp(name: str) -> sa.Column[object]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_email", sa.String(length=254), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_invitations")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_invitations_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["users.id"],
            name=op.f("fk_organization_invitations_invited_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("token_hash", name=op.f("uq_organization_invitations_token_hash")),
        sa.CheckConstraint(
            "role IN ('admin', 'member', 'viewer')",
            name=op.f("ck_organization_invitations_invitation_role"),
        ),
        sa.CheckConstraint(
            "btrim(normalized_email) <> ''",
            name=op.f("ck_organization_invitations_normalized_email_not_blank"),
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_organization_invitations_token_hash_is_sha256_hex"),
        ),
        sa.CheckConstraint(
            "accepted_at IS NULL OR revoked_at IS NULL",
            name=op.f("ck_organization_invitations_not_accepted_and_revoked"),
        ),
    )
    for column in INDEXED:
        op.create_index(op.f(f"ix_{TABLE}_{column}"), TABLE, [column], unique=False)


def downgrade() -> None:
    for column in reversed(INDEXED):
        op.drop_index(op.f(f"ix_{TABLE}_{column}"), table_name=TABLE)
    op.drop_table(TABLE)
