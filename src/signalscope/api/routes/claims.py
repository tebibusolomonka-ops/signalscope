import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import StringConstraints

from signalscope.api.dependencies import DatabaseSession, DatabaseSessionFactory
from signalscope.api.pagination import Page, Pagination
from signalscope.api.tenancy import OrganizationFilter, Policy, ReadScope
from signalscope.core.errors import NotFoundError
from signalscope.domain.claims.coverage import ClaimCoverageService
from signalscope.domain.claims.model import CLAIM_TEXT_MAX_LENGTH, CLAIM_TYPE_MAX_LENGTH, Claim
from signalscope.domain.claims.repository import ClaimRepository
from signalscope.domain.claims.schemas import (
    ClaimCoverageRead,
    ClaimDetailRead,
    ClaimEvidenceRead,
    ClaimRead,
)
from signalscope.extraction.gliner2 import GLINER2_MODEL, GLINER2_PROVIDER

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
    scope: ReadScope,
    query: TextQuery = None,
    claim_type: TypeQuery = None,
) -> Page[ClaimRead]:
    """List claims found in documents, by text. Claims are read only.

    Nothing here says whether a claim is true. With authentication on, only
    claims with evidence in the organization_id organization, counting that.
    """
    summaries, total = await ClaimRepository(session).list_page(
        query, claim_type, page.limit, page.offset, scope
    )
    return Page[ClaimRead](
        items=[_claim_read(summary.claim, summary.evidence_count) for summary in summaries],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


# Declared before /{claim_id}, so "coverage" is not read as a claim ID.
@router.get("/coverage")
async def claim_coverage(
    session_factory: DatabaseSessionFactory,
    policy: Policy,
    organization_id: OrganizationFilter = None,
    document_id: uuid.UUID | None = None,
) -> ClaimCoverageRead:
    """Count the chunks the local GLiNER2 model has read for claims.

    The numbers come from the database, so the model does not need to be
    installed or loaded. document_id limits them to one document. With
    authentication on, the counts cover the organization_id organization, or
    the document's organization when document_id is given.
    """
    service = ClaimCoverageService(session_factory)
    if document_id is None:
        scope = await policy.scope(organization_id)
        coverage = await service.overall(GLINER2_PROVIDER, GLINER2_MODEL, scope)
    else:
        await policy.authorize_document(document_id)
        coverage = await service.for_document(document_id, GLINER2_PROVIDER, GLINER2_MODEL)
    return ClaimCoverageRead(
        provider=GLINER2_PROVIDER,
        model=GLINER2_MODEL,
        document_id=document_id,
        chunk_count=coverage.chunk_count,
        extracted_count=coverage.extracted_count,
        pending_count=coverage.pending_count,
        failed_count=coverage.failed_count,
        coverage_ratio=(
            coverage.extracted_count / coverage.chunk_count if coverage.chunk_count else None
        ),
    )


@router.get("/{claim_id}")
async def get_claim(
    claim_id: uuid.UUID, session: DatabaseSession, scope: ReadScope
) -> ClaimDetailRead:
    """One claim with the passages that make it, the first 100 in document order.

    With authentication on, only evidence in the organization_id
    organization; a claim without any there is not found.
    """
    repository = ClaimRepository(session)
    claim = await repository.get(claim_id)
    if claim is None:
        raise NotFoundError("Claim was not found.")
    evidence, total = await repository.evidence(claim_id, scope=scope)
    if total == 0 and not scope.is_unrestricted:
        raise NotFoundError("Claim was not found.")
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
