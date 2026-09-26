"""Create claims

Revision ID: e6554a64a987
Revises: 87d6fdd9beaa
Create Date: 2026-09-27 00:45:33.975824

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e6554a64a987"
down_revision: str | Sequence[str] | None = "87d6fdd9beaa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        )
        for name in ("created_at", "updated_at")
    ]


def upgrade() -> None:
    op.create_table(
        "claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.String(length=500), nullable=False),
        sa.Column("normalized_text", sa.String(length=500), nullable=False),
        sa.Column("claim_type", sa.String(length=50), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claims")),
        sa.UniqueConstraint(
            "normalized_text", "claim_type", name=op.f("uq_claims_normalized_text_claim_type")
        ),
        sa.CheckConstraint("btrim(text) <> ''", name=op.f("ck_claims_text_not_blank")),
        sa.CheckConstraint(
            "btrim(normalized_text) <> ''", name=op.f("ck_claims_normalized_text_not_blank")
        ),
        sa.CheckConstraint("btrim(claim_type) <> ''", name=op.f("ck_claims_claim_type_not_blank")),
    )
    op.create_table(
        "claim_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("surface_text", sa.String(length=2000), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_evidence")),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.id"],
            name=op.f("fk_claim_evidence_claim_id_claims"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.id"],
            name=op.f("fk_claim_evidence_chunk_id_document_chunks"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "chunk_id",
            "start_char",
            "end_char",
            "provider",
            "model",
            name=op.f("uq_claim_evidence_chunk_id_start_char_end_char_provider_model"),
        ),
        sa.CheckConstraint(
            "start_char >= 0", name=op.f("ck_claim_evidence_start_char_not_negative")
        ),
        sa.CheckConstraint(
            "end_char > start_char", name=op.f("ck_claim_evidence_end_char_after_start_char")
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_claim_evidence_confidence_between_zero_and_one"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'", name=op.f("ck_claim_evidence_metadata_is_object")
        ),
    )
    op.create_index(
        op.f("ix_claim_evidence_claim_id"), "claim_evidence", ["claim_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_claim_evidence_claim_id"), table_name="claim_evidence")
    op.drop_table("claim_evidence")
    op.drop_table("claims")
