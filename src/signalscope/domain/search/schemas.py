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
