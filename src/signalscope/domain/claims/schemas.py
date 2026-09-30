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
    # The document title and the source it came from, for a readable summary.
    document_title: str | None
    source_id: uuid.UUID
    source_name: str
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


class ClaimCoverageRead(BaseModel):
    """How many chunks the local claim model has read."""

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
