import uuid

from fastapi import APIRouter, Response, status

from signalscope.api.dependencies import (
    AnswerGenerators,
    DatabaseSession,
    EmbeddingProviders,
    Rerankers,
)
from signalscope.core.exports import MARKDOWN_MEDIA_TYPE, ExportFormat
from signalscope.domain.research.export import (
    ResearchSessionExport,
    ResearchSessionExportService,
    session_markdown,
)
from signalscope.domain.research.schemas import (
    ResearchSessionCreate,
    ResearchSessionRead,
    ResearchTurnCreate,
    ResearchTurnRead,
    ResearchTurnResponse,
)
from signalscope.domain.research.service import ResearchSessionService
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

    Answers 503 unless local answers are enabled, which they are not by default. When
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


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_research_session(
    request: ResearchSessionCreate,
    session: DatabaseSession,
    providers: EmbeddingProviders,
    rerankers: Rerankers,
    generators: AnswerGenerators,
) -> ResearchSessionRead:
    """Start a research session. Every turn in it searches with its mode and source."""
    service = ResearchSessionService(session, providers, rerankers, generators)
    research = await service.create_session(
        title=request.title, retrieval_mode=request.retrieval_mode, source_id=request.source_id
    )
    return ResearchSessionRead.model_validate(research)


@router.get("/sessions/{session_id}")
async def get_research_session(
    session_id: uuid.UUID,
    session: DatabaseSession,
    providers: EmbeddingProviders,
    rerankers: Rerankers,
    generators: AnswerGenerators,
) -> ResearchSessionRead:
    service = ResearchSessionService(session, providers, rerankers, generators)
    return ResearchSessionRead.model_validate(await service.get_session(session_id))


@router.get("/sessions/{session_id}/turns")
async def list_research_turns(
    session_id: uuid.UUID,
    session: DatabaseSession,
    providers: EmbeddingProviders,
    rerankers: Rerankers,
    generators: AnswerGenerators,
) -> list[ResearchTurnRead]:
    """Every turn of a session, oldest first, with the evidence each was answered from."""
    service = ResearchSessionService(session, providers, rerankers, generators)
    return [ResearchTurnRead.from_turn(turn) for turn in await service.list_turns(session_id)]


@router.get(
    "/sessions/{session_id}/export",
    response_model=ResearchSessionExport,
    responses={200: {"content": {"text/markdown": {}}}},
)
async def export_research_session(
    session_id: uuid.UUID, session: DatabaseSession, format: ExportFormat = ExportFormat.JSON
) -> ResearchSessionExport | Response:
    """The whole session: every turn with its answer, citations and the evidence it saw.

    The evidence is what each turn saved at the time; nothing is searched again.
    format=markdown returns the same content as Markdown text. Nothing is
    written on the server.
    """
    export = await ResearchSessionExportService(session).export(session_id)
    if format is ExportFormat.MARKDOWN:
        return Response(session_markdown(export), media_type=MARKDOWN_MEDIA_TYPE)
    return export


@router.post("/sessions/{session_id}/turns", status_code=status.HTTP_201_CREATED)
async def add_research_turn(
    session_id: uuid.UUID,
    request: ResearchTurnCreate,
    session: DatabaseSession,
    providers: EmbeddingProviders,
    rerankers: Rerankers,
    generators: AnswerGenerators,
) -> ResearchTurnResponse:
    """Ask the next question in a session.

    The question gets its own evidence search. Earlier turns are given to the
    answer model as conversation context, not as evidence: the answer can only
    cite this turn's evidence, and its citations are checked. Without an answer
    model the turn is saved with its evidence and no answer.
    """
    service = ResearchSessionService(session, providers, rerankers, generators)
    turn = await service.add_turn(session_id, request.question, request.limit)
    research = await service.get_session(session_id)
    return ResearchTurnResponse(
        session=ResearchSessionRead.model_validate(research),
        turn=ResearchTurnRead.from_turn(turn),
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
