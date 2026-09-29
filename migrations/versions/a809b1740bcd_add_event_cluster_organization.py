"""Add event cluster organization

Revision ID: a809b1740bcd
Revises: 8a83722f5691
Create Date: 2026-09-30 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a809b1740bcd"
down_revision: str | Sequence[str] | None = "8a83722f5691"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A cluster gets an organization only when every piece of evidence of every
# member comes from that one organization. Legacy clusters, and clusters that
# already mix organizations, keep NULL; nothing is guessed.
BACKFILL = """
UPDATE event_clusters AS cluster
SET organization_id = owners.organization_id
FROM (
    SELECT
        member.cluster_id,
        (array_agg(source.organization_id))[1] AS organization_id
    FROM event_cluster_members AS member
    JOIN event_evidence AS evidence ON evidence.event_id = member.event_id
    JOIN document_chunks AS chunk ON chunk.id = evidence.chunk_id
    JOIN documents AS document ON document.id = chunk.document_id
    JOIN sources AS source ON source.id = document.source_id
    GROUP BY member.cluster_id
    HAVING count(DISTINCT source.organization_id) = 1
        AND count(*) = count(source.organization_id)
) AS owners
WHERE cluster.id = owners.cluster_id
"""


def upgrade() -> None:
    op.add_column("event_clusters", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_event_clusters_organization_id_organizations"),
        "event_clusters",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_event_clusters_organization_id"),
        "event_clusters",
        ["organization_id"],
        unique=False,
    )
    op.execute(BACKFILL)


def downgrade() -> None:
    op.drop_index(op.f("ix_event_clusters_organization_id"), table_name="event_clusters")
    op.drop_constraint(
        op.f("fk_event_clusters_organization_id_organizations"),
        "event_clusters",
        type_="foreignkey",
    )
    op.drop_column("event_clusters", "organization_id")
