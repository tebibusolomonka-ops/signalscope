import uuid
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints

from signalscope.domain.search.service import MAX_QUERY_LENGTH
from signalscope.research.evidence import (
    DEFAULT_EVIDENCE_LIMIT,
    MAX_EVIDENCE_LIMIT,
    ResearchMode,
)


class ResearchContextRequest(BaseModel):
    query: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUERY_LENGTH)
    ]
    mode: ResearchMode = ResearchMode.HYBRID
    limit: Annotated[int, Field(ge=1, le=MAX_EVIDENCE_LIMIT)] = DEFAULT_EVIDENCE_LIMIT
    source_id: uuid.UUID | None = None


class ResearchEvidenceRead(BaseModel):
    """One piece of evidence. The full chunk text is in context_text only."""

    evidence_id: str
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    title: str | None
    url: str | None
    excerpt: str
    chunk_metadata: dict[str, Any]
    scores: dict[str, float | int | None]


class ResearchContextResponse(BaseModel):
    query: str
    mode: ResearchMode
    evidence: list[ResearchEvidenceRead]
    # The evidence as numbered blocks, ready to give to a language model.
    context_text: str


class ResearchAnswerRequest(ResearchContextRequest):
    pass


class GeneratedAnswerRead(BaseModel):
    text: str
    # The IDs the text cites, such as E1. Each one is in citations.
    citation_ids: list[str]


class CitationRead(BaseModel):
    """Where one cited evidence ID points to."""

    citation_id: str
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    title: str | None
    url: str | None
    chunk_metadata: dict[str, Any]


class ResearchAnswerResponse(BaseModel):
    query: str
    mode: ResearchMode
    # None when no evidence was found. No answer is written without evidence.
    answer: GeneratedAnswerRead | None
    # The cited evidence, in the order of citation_ids.
    citations: list[CitationRead]
    # All the evidence the answer model was given.
    evidence: list[ResearchEvidenceRead]
