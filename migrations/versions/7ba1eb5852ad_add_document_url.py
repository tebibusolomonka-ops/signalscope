"""Add document url

Revision ID: 7ba1eb5852ad
Revises: 8eeb5be26820
Create Date: 2026-09-25 11:38:53.813354

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7ba1eb5852ad"
down_revision: str | Sequence[str] | None = "8eeb5be26820"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("url", sa.String(length=2048), nullable=True))
    op.create_index("ix_documents_source_id_url", "documents", ["source_id", "url"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_documents_source_id_url", table_name="documents")
    op.drop_column("documents", "url")
