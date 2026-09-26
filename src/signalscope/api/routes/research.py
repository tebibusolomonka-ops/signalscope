from fastapi import APIRouter

from signalscope.api.dependencies import DatabaseSession, EmbeddingProviders, Rerankers
from signalscope.research.context import context_text
from signalscope.research.evidence import ResearchEvidenceService
from signalscope.research.schemas import (
    ResearchContextRequest,
    ResearchContextResponse,
    ResearchEvidenceRead,
)

router = APIRouter(prefix="/research", tags=["Research"])


@router.post("/context")
async def research_context(
    request: ResearchContextRequest,
    session: DatabaseSession,
    providers: EmbeddingProviders,
    rerankers: Rerankers,
) -> ResearchContextResponse:
    """Collect cited evidence for a query, ready for a later answer step.

    This only retrieves and arranges evidence. It does not write an answer or a
    summary. The reranked mode answers 503 when local reranking is off, and the
    semantic, hybrid and reranked modes when local embeddings are off.
    """
    evidence = await ResearchEvidenceService(session, providers, rerankers).build(
        request.query, mode=request.mode, limit=request.limit, source_id=request.source_id
    )
    return ResearchContextResponse(
        query=request.query,
        mode=request.mode,
        evidence=[
            ResearchEvidenceRead(
                evidence_id=item.evidence_id,
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                source_id=item.source_id,
                title=item.title,
                url=item.url,
                excerpt=item.excerpt,
                chunk_metadata=item.chunk_metadata,
                scores=item.scores,
            )
            for item in evidence
        ],
        context_text=context_text(evidence),
    )
