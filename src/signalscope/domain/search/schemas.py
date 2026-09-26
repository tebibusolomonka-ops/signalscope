import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict


class SearchResultRead(BaseModel):
    """One matching chunk. The excerpt stands in for the full text."""

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    title: str | None
    url: str | None
    excerpt: str
    rank: float
    # Where the chunk came from, such as {"page_number": 3}.
    chunk_metadata: dict[str, Any]


class SearchResponse(BaseModel):
    items: list[SearchResultRead]


class SemanticSearchResultRead(BaseModel):
    """One chunk close to the query. The vectors themselves are left out."""

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    title: str | None
    url: str | None
    chunk_metadata: dict[str, Any]
    # 1 minus the cosine distance: 1 is the same direction, -1 the opposite.
    similarity: float


class SemanticSearchResponse(BaseModel):
    items: list[SemanticSearchResultRead]


class HybridSearchResultRead(BaseModel):
    """One chunk from full text search, vector search or both."""

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    title: str | None
    url: str | None
    # Only set when full text search found the chunk.
    excerpt: str | None
    chunk_metadata: dict[str, Any]
    # The 1-based place in the full text results, when the chunk is there.
    lexical_rank: int | None
    # 1 minus the cosine distance, when vector search found the chunk.
    vector_similarity: float | None
    # The Reciprocal Rank Fusion score. Higher is better.
    hybrid_score: float


class HybridSearchResponse(BaseModel):
    items: list[HybridSearchResultRead]


class EmbeddingCoverageRead(BaseModel):
    """How many chunks have a current embedding from one model."""

    provider: str
    model: str
    # Set when the numbers are for one document only.
    document_id: uuid.UUID | None
    chunk_count: int
    embedded_count: int
    pending_count: int
    failed_count: int
    # embedded_count / chunk_count, or None when there are no chunks.
    coverage: float | None
