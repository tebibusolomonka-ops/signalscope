import uuid

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


class SearchResponse(BaseModel):
    items: list[SearchResultRead]
