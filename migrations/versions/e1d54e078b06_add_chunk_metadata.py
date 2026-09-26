"""Add chunk metadata

Revision ID: e1d54e078b06
Revises: a657be153fd5
Create Date: 2026-09-26 14:29:39.210627

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1d54e078b06"
down_revision: str | Sequence[str] | None = "a657be153fd5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_document_chunks_metadata_is_object"),
        "document_chunks",
        "jsonb_typeof(metadata) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_document_chunks_metadata_is_object"), "document_chunks", type_="check"
    )
    op.drop_column("document_chunks", "metadata")
