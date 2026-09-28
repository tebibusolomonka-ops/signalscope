import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    title: str
    summary: str | None
    occurred_at: datetime | None
    created_at: datetime


class EventEvidenceRead(BaseModel):
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    confidence: float | None
    provider: str
    model: str
    # Where the chunk came from, such as {"page_number": 3}.
    chunk_metadata: dict[str, Any]


class EventDetailRead(BaseModel):
    event: EventRead
    # At most the first 100 evidence rows, in document order.
    evidence: list[EventEvidenceRead]


class EventCoverageRead(BaseModel):
    """How many chunks the local event model has read."""

    provider: str
    model: str
    # Set when the numbers are for one document only.
    document_id: uuid.UUID | None
    chunk_count: int
    extracted_count: int
    pending_count: int
    failed_count: int
    # extracted_count / chunk_count, or None when there are no chunks.
    coverage_ratio: float | None


class TimelineSourceRead(BaseModel):
    source_id: uuid.UUID
    name: str


class TimelineItemRead(BaseModel):
    """One cluster of linked events on the timeline."""

    cluster_id: uuid.UUID
    event_type: str
    title: str
    occurred_at: datetime | None
    event_count: int
    source_count: int
    evidence_count: int
    # The sources that report it, by name.
    sources: list[TimelineSourceRead]


class EventLinkSuggestionRead(BaseModel):
    """An event that may report the same thing. Advisory only: nothing is linked."""

    candidate_event_id: uuid.UUID
    # The cluster the candidate is in, if any.
    candidate_cluster_id: uuid.UUID | None
    title: str
    occurred_at: datetime | None
    # Cosine similarity of the two event texts, from -1 to 1. Not a probability.
    similarity: float


class ClusterEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    confidence: float | None
    provider: str
    model: str
    # Where the chunk came from, such as {"page_number": 3}.
    chunk_metadata: dict[str, Any]


class ClusterMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: uuid.UUID
    title: str
    summary: str | None
    occurred_at: datetime | None
    created_at: datetime
    evidence: list[ClusterEvidenceRead]


class EventClusterDetailRead(BaseModel):
    """One event cluster with its member events and where each was reported."""

    model_config = ConfigDict(from_attributes=True)

    cluster_id: uuid.UUID
    event_type: str
    title: str
    occurred_at: datetime | None
    event_count: int
    source_count: int
    # All evidence rows. The members list at most the first 500.
    evidence_count: int
    members: list[ClusterMemberRead]
