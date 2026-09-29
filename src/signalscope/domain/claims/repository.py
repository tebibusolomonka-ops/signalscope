import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.claims.text import normalize_claim_text, normalize_claim_type
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.tenancy.scope import ContentScope

# The most evidence rows a claim detail shows. evidence_count still counts them all.
MAX_DETAIL_EVIDENCE = 100
UNRESTRICTED = ContentScope.unrestricted()


@dataclass(frozen=True, slots=True)
class ClaimSummary:
    claim: Claim
    evidence_count: int


@dataclass(frozen=True, slots=True)
class EvidenceWithChunk:
    evidence: ClaimEvidence
    document_id: uuid.UUID
    # Where the chunk came from, such as {"page_number": 3}.
    chunk_metadata: dict[str, Any]


class ClaimRepository:
    """Read access to claims and their evidence. It never commits.

    Claims are shared rows, not owned by an organization. In a scope, a claim
    is only seen through its evidence in that scope: it is listed when it has
    some, and its counts and evidence come from that only.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_page(
        self,
        query: str | None,
        claim_type: str | None,
        limit: int,
        offset: int,
        scope: ContentScope = UNRESTRICTED,
    ) -> tuple[list[ClaimSummary], int]:
        """Claims whose normalized text contains the normalized query, by text.

        This is plain substring matching, not search by meaning. Unrestricted,
        every claim is listed, also without evidence, as before organizations.
        """
        conditions = _conditions(query, claim_type)
        visible = scope.chunk_condition(ClaimEvidence.chunk_id)
        evidence_counts = (
            select(ClaimEvidence.claim_id, func.count().label("evidence"))
            .where(visible)
            .group_by(ClaimEvidence.claim_id)
            .subquery()
        )
        if scope.is_unrestricted:
            statement = select(Claim, func.coalesce(evidence_counts.c.evidence, 0)).outerjoin(
                evidence_counts, evidence_counts.c.claim_id == Claim.id
            )
        else:
            statement = select(Claim, evidence_counts.c.evidence).join(
                evidence_counts, evidence_counts.c.claim_id == Claim.id
            )
            conditions.append(
                Claim.id.in_(select(ClaimEvidence.claim_id).where(visible).correlate(None))
            )
        rows = await self.session.execute(
            statement.where(*conditions)
            .order_by(Claim.normalized_text, Claim.claim_type, Claim.id)
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(
            select(func.count()).select_from(Claim).where(*conditions)
        )
        return [ClaimSummary(claim, count) for claim, count in rows], total or 0

    async def get(self, claim_id: uuid.UUID) -> Claim | None:
        return await self.session.get(Claim, claim_id)

    async def evidence(
        self,
        claim_id: uuid.UUID,
        limit: int = MAX_DETAIL_EVIDENCE,
        scope: ContentScope = UNRESTRICTED,
    ) -> tuple[list[EvidenceWithChunk], int]:
        """The evidence of a claim in scope, in document order, and how much there is."""
        visible = scope.chunk_condition(ClaimEvidence.chunk_id)
        rows = await self.session.execute(
            select(ClaimEvidence, DocumentChunk.document_id, DocumentChunk.chunk_metadata)
            .join(DocumentChunk, DocumentChunk.id == ClaimEvidence.chunk_id)
            .where(ClaimEvidence.claim_id == claim_id, visible)
            .order_by(DocumentChunk.document_id, DocumentChunk.position, ClaimEvidence.start_char)
            .limit(limit)
        )
        total = await self.session.scalar(
            select(func.count())
            .select_from(ClaimEvidence)
            .where(ClaimEvidence.claim_id == claim_id, visible)
        )
        items = [
            EvidenceWithChunk(evidence, document_id, dict(metadata))
            for evidence, document_id, metadata in rows
        ]
        return items, total or 0


def _conditions(query: str | None, claim_type: str | None) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if query is not None:
        # The query is taken as plain text, so % and _ have no special meaning.
        conditions.append(
            Claim.normalized_text.contains(normalize_claim_text(query), autoescape=True)
        )
    if claim_type is not None:
        conditions.append(Claim.claim_type == normalize_claim_type(claim_type))
    return conditions
