import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from signalscope.domain.research.session import SESSION_TITLE_MAX_LENGTH
from signalscope.domain.research.turn import ResearchTurn
from signalscope.domain.search.service import MAX_QUERY_LENGTH
from signalscope.research.evidence import DEFAULT_EVIDENCE_LIMIT, MAX_EVIDENCE_LIMIT, ResearchMode


class ResearchSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=SESSION_TITLE_MAX_LENGTH),
    ] = None
    # How every turn in the session searches.
    retrieval_mode: ResearchMode = ResearchMode.HYBRID
    # When set, every turn only searches this source.
    source_id: uuid.UUID | None = None
    # Required when authentication is on; not allowed when it is off.
    organization_id: uuid.UUID | None = None


class ResearchSessionStart(ResearchSessionCreate):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUERY_LENGTH)
    ]


class ResearchSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    retrieval_mode: ResearchMode
    source_id: uuid.UUID | None
    # None for legacy sessions, from before organizations.
    organization_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ResearchTurnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUERY_LENGTH)
    ]
    limit: Annotated[int, Field(ge=1, le=MAX_EVIDENCE_LIMIT)] = DEFAULT_EVIDENCE_LIMIT


class TurnEvidenceRead(BaseModel):
    """One piece of the evidence a turn was answered from, as it was then."""

    evidence_id: str
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    title: str | None
    url: str | None
    excerpt: str
    chunk_metadata: dict[str, Any]


class ResearchTurnRead(BaseModel):
    id: uuid.UUID
    sequence: int
    question: str
    # None when no answer model is configured, or no evidence was found.
    answer: str | None
    citation_ids: list[str]
    # The cited evidence, in the order of citation_ids.
    citations: list[TurnEvidenceRead]
    # All the evidence found for this question.
    evidence: list[TurnEvidenceRead]
    created_at: datetime

    @classmethod
    def from_turn(cls, turn: ResearchTurn) -> "ResearchTurnRead":
        evidence = [TurnEvidenceRead.model_validate(item) for item in turn.evidence_snapshot]
        by_id = {item.evidence_id: item for item in evidence}
        return cls(
            id=turn.id,
            sequence=turn.sequence,
            question=turn.question,
            answer=turn.answer,
            citation_ids=list(turn.citation_ids),
            citations=[by_id[citation_id] for citation_id in turn.citation_ids],
            evidence=evidence,
            created_at=turn.created_at,
        )


class ResearchTurnResponse(BaseModel):
    session: ResearchSessionRead
    turn: ResearchTurnRead
