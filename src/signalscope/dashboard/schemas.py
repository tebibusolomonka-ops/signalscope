import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict


class DashboardOverviewRead(BaseModel):
    """Record counts and open queue work. Counts only; nothing is scored or ranked."""

    model_config = ConfigDict(from_attributes=True)

    sources: int
    documents: int
    chunks: int
    entities: int
    claims: int
    events: int
    event_clusters: int
    research_sessions: int
    investigations: int
    # Jobs waiting or running.
    pending_ingestion: int
    pending_processing: int
    pending_embeddings: int
    pending_entities: int
    pending_events: int
    pending_claims: int


class SourceActivityDayRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    documents_created: int
    documents_published: int


class SourceActivityRead(BaseModel):
    days: int
    source_id: uuid.UUID | None
    # One entry per UTC day, oldest first, ending today.
    items: list[SourceActivityDayRead]


class EventActivityDayRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    events: int
    clusters: int
    cross_source_clusters: int


class EventActivityRead(BaseModel):
    days: int
    event_type: str | None
    source_id: uuid.UUID | None
    # One entry per UTC day, oldest first, ending today.
    items: list[EventActivityDayRead]
