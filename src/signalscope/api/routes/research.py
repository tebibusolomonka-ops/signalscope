from fastapi import APIRouter

from signalscope.api.dependencies import (
    AnswerGenerators,
    DatabaseSession,
    EmbeddingProviders,
    Rerankers,
)
from signalscope.research.answering import ResearchAnswerService
from signalscope.research.context import context_text
from signalscope.research.evidence import ResearchEvidence, ResearchEvidenceService
from signalscope.research.schemas import (
    CitationRead,
    GeneratedAnswerRead,
    ResearchAnswerRequest,
    ResearchAnswerResponse,
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
        evidence=[_evidence_read(item) for item in evidence],
        context_text=context_text(evidence),
    )


@router.post("/answer")
async def research_answer(
    request: ResearchAnswerRequest,
    session: DatabaseSession,
    providers: EmbeddingProviders,
    rerankers: Rerankers,
    generators: AnswerGenerators,
) -> ResearchAnswerResponse:
    """Answer a question from retrieved evidence, with checked citations.

    Answers 503 while no answer model is configured, which is the default. When
    no evidence is found, the model is not asked and answer is null. An answer
    whose citations do not match the evidence is never returned: the request
    fails with 503 instead.
    """
    result = await ResearchAnswerService(session, providers, rerankers, generators).answer(
        request.query, mode=request.mode, limit=request.limit, source_id=request.source_id
    )
    return ResearchAnswerResponse(
        query=request.query,
        mode=request.mode,
        answer=None
        if result.answer is None
        else GeneratedAnswerRead(
            text=result.answer.text, citation_ids=list(result.answer.citation_ids)
        ),
        citations=[
            CitationRead(
                citation_id=item.evidence_id,
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                source_id=item.source_id,
                title=item.title,
                url=item.url,
                chunk_metadata=item.chunk_metadata,
            )
            for item in result.cited
        ],
        evidence=[_evidence_read(item) for item in result.evidence],
    )


def _evidence_read(item: ResearchEvidence) -> ResearchEvidenceRead:
    return ResearchEvidenceRead(
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
