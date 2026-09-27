import uuid
from datetime import datetime
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from signalscope.domain.sources.model import (
    MAX_INGESTION_INTERVAL_MINUTES,
    SOURCE_NAME_MAX_LENGTH,
    SourceType,
)

URL_MAX_LENGTH = 2048
TYPES_THAT_NEED_URL = frozenset({SourceType.WEB, SourceType.RSS})


class SourceCreate(BaseModel):
    # Unknown fields such as id or created_at are rejected instead of ignored.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: SourceType
    name: str = Field(min_length=1, max_length=SOURCE_NAME_MAX_LENGTH)
    url: str | None = Field(default=None, min_length=1, max_length=URL_MAX_LENGTH)

    @model_validator(mode="after")
    def check_url(self) -> Self:
        if self.url is None and self.type in TYPES_THAT_NEED_URL:
            raise ValueError(f"url is required for {self.type} sources")
        return self


class SourceScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval_minutes: int = Field(ge=1, le=MAX_INGESTION_INTERVAL_MINUTES)
    # Without a start time, the first ingestion is due right away.
    start_at: AwareDatetime | None = None


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: SourceType
    name: str
    url: str | None
    ingestion_enabled: bool
    ingestion_interval_minutes: int | None
    next_ingestion_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SourceProvenanceRead(BaseModel):
    """What SignalScope has observed about a source.

    These are counts and dates, not a credibility score.
    """

    model_config = ConfigDict(from_attributes=True)

    source_id: uuid.UUID
    document_count: int
    first_document_at: datetime | None
    last_document_at: datetime | None
    first_published_at: datetime | None
    last_published_at: datetime | None
    entity_count: int
    claim_count: int
    event_count: int
    event_cluster_count: int
    # Clusters of its events that at least one other source also reports.
    cross_source_event_cluster_count: int
    revision_count: int
