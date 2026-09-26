import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import StringConstraints

from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.core.errors import NotFoundError
from signalscope.domain.claims.model import CLAIM_TEXT_MAX_LENGTH, CLAIM_TYPE_MAX_LENGTH, Claim
from signalscope.domain.claims.repository import ClaimRepository
from signalscope.domain.claims.schemas import ClaimDetailRead, ClaimEvidenceRead, ClaimRead

router = APIRouter(prefix="/claims", tags=["Claims"])

TextQuery = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=CLAIM_TEXT_MAX_LENGTH),
    Query(description="Part of the claim text, in any case."),
]
TypeQuery = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=CLAIM_TYPE_MAX_LENGTH),
    Query(description="The claim type, such as statistic. Case does not matter."),
]


@router.get("")
async def list_claims(
    session: DatabaseSession,
    page: Pagination,
    query: TextQuery = None,
    claim_type: TypeQuery = None,
) -> Page[ClaimRead]:
    """List claims found in documents, by text. Claims are read only.

    Nothing here says whether a claim is true.
    """
    summaries, total = await ClaimRepository(session).list_page(
        query, claim_type, page.limit, page.offset
    )
    return Page[ClaimRead](
        items=[_claim_read(summary.claim, summary.evidence_count) for summary in summaries],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{claim_id}")
async def get_claim(claim_id: uuid.UUID, session: DatabaseSession) -> ClaimDetailRead:
    """One claim with the passages that make it, the first 100 in document order."""
    repository = ClaimRepository(session)
    claim = await repository.get(claim_id)
    if claim is None:
        raise NotFoundError("Claim was not found.")
    evidence, total = await repository.evidence(claim_id)
    return ClaimDetailRead(
        claim=_claim_read(claim, total),
        evidence_count=total,
        evidence=[
            ClaimEvidenceRead(
                id=item.evidence.id,
                document_id=item.document_id,
                chunk_id=item.evidence.chunk_id,
                surface_text=item.evidence.surface_text,
                start_char=item.evidence.start_char,
                end_char=item.evidence.end_char,
                confidence=item.evidence.confidence,
                provider=item.evidence.provider,
                model=item.evidence.model,
                chunk_metadata=item.chunk_metadata,
            )
            for item in evidence
        ],
    )


def _claim_read(claim: Claim, evidence_count: int) -> ClaimRead:
    return ClaimRead(
        id=claim.id,
        text=claim.text,
        normalized_text=claim.normalized_text,
        claim_type=claim.claim_type,
        evidence_count=evidence_count,
        created_at=claim.created_at,
    )
