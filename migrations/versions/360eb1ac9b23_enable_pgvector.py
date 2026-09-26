"""Enable pgvector

Revision ID: 360eb1ac9b23
Revises: e1d54e078b06
Create Date: 2026-09-26 15:06:43.509367

"""

from collections.abc import Sequence

from alembic import op

revision: str = "360eb1ac9b23"
down_revision: str | Sequence[str] | None = "e1d54e078b06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # The extension is left installed. Dropping it would also drop every
    # vector column and index in the database, including any that another
    # migration or another application made.
    pass
