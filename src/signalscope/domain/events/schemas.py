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
