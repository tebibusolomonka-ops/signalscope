import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ClaimRead(BaseModel):
    id: uuid.UUID
    text: str
    normalized_text: str
    claim_type: str
    evidence_count: int
    created_at: datetime


class ClaimEvidenceRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    surface_text: str
    # Offsets into the chunk text.
    start_char: int
    end_char: int
    confidence: float | None
    provider: str
    model: str
    # Where the chunk came from, such as {"page_number": 3}.
    chunk_metadata: dict[str, Any]


class ClaimDetailRead(BaseModel):
    claim: ClaimRead
    evidence_count: int
    # At most the first 100 evidence rows, in document order.
    evidence: list[ClaimEvidenceRead]
