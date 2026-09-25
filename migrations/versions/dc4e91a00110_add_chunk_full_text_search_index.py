"""Add chunk full text search index

Revision ID: dc4e91a00110
Revises: 82bd0e6285b0
Create Date: 2026-09-25 22:24:53.332711

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "dc4e91a00110"
down_revision: str | Sequence[str] | None = "82bd0e6285b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_document_chunks_text_search",
        "document_chunks",
        [sa.text("to_tsvector('simple'::regconfig, text)")],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_text_search", table_name="document_chunks")
