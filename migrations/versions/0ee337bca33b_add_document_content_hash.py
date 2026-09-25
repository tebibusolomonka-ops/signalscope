"""Add document content hash

Revision ID: 0ee337bca33b
Revises: 7ba1eb5852ad
Create Date: 2026-09-25 12:06:54.391787

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0ee337bca33b"
down_revision: str | Sequence[str] | None = "7ba1eb5852ad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.create_unique_constraint(
        op.f("uq_documents_source_id_content_hash"), "documents", ["source_id", "content_hash"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_documents_source_id_content_hash"), "documents", type_="unique")
    op.drop_column("documents", "content_hash")
