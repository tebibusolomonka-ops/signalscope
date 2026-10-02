import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class EntityRead(BaseModel):
    id: uuid.UUID
    canonical_name: str
    normalized_name: str
    entity_type: str
    mention_count: int
    created_at: datetime


class EntityMentionRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_title: str | None
    source_id: uuid.UUID
    source_name: str
    chunk_id: uuid.UUID
    surface_text: str
    entity_type: str
    # Offsets into the chunk text.
    start_char: int
    end_char: int
    confidence: float | None
    provider: str
    model: str
    # Where the chunk came from, such as {"page_number": 3}.
    chunk_metadata: dict[str, Any]


class EntityDetailRead(BaseModel):
    entity: EntityRead
    mention_count: int
    # At most the first 100 mentions, in document order.
    mentions: list[EntityMentionRead]


class EntityCoverageRead(BaseModel):
    """How many chunks the local entity model has read."""

    provider: str
    model: str
    # Set when the numbers are for one document only.
    document_id: uuid.UUID | None
    chunk_count: int
    extracted_count: int
    pending_count: int
    failed_count: int
    # extracted_count / chunk_count, or None when there are no chunks.
    coverage: float | None
