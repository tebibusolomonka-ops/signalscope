import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.search.repository import MAX_SEARCH_LIMIT


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    source_id: uuid.UUID
    title: str | None
    url: str | None
    # Where the chunk came from, such as {"page_number": 3}.
    chunk_metadata: dict[str, Any]
    # Cosine distance from the query: 0 is the same direction, 2 the opposite.
    distance: float

    @property
    def similarity(self) -> float:
        return 1 - self.distance


class VectorSearchRepository:
    """Exact nearest neighbour search over chunk embeddings with pgvector.

    Vectors from different models cannot be compared, so only embeddings from
    one provider and model, with the query's number of dimensions, are
    searched. Embeddings made from older chunk text are left out. There is no
    vector index yet, so every matching embedding is compared.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self,
        vector: Sequence[float],
        *,
        provider: str,
        model: str,
        dimensions: int,
        limit: int,
        source_id: uuid.UUID | None = None,
    ) -> list[VectorSearchResult]:
        """Return the closest chunks, smallest cosine distance first."""
        if not 1 <= limit <= MAX_SEARCH_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}")
        if len(vector) != dimensions:
            raise ValueError(f"vector has {len(vector)} dimensions instead of {dimensions}")
        distance = ChunkEmbedding.embedding.cosine_distance(list(vector))
        statement = (
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                Document.source_id,
                Document.title,
                Document.url,
                DocumentChunk.chunk_metadata,
                distance,
            )
            .select_from(ChunkEmbedding)
            .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                ChunkEmbedding.provider == provider,
                ChunkEmbedding.model == model,
                ChunkEmbedding.dimensions == dimensions,
                ChunkEmbedding.chunk_text_hash == DocumentChunk.text_hash,
            )
            # Chunks at the same distance keep the order they have in their documents.
            .order_by(distance, DocumentChunk.document_id, DocumentChunk.position)
            .limit(limit)
        )
        if source_id is not None:
            statement = statement.where(Document.source_id == source_id)
        rows = (await self.session.execute(statement)).all()
        return [
            VectorSearchResult(
                chunk_id=chunk_id,
                document_id=document_id,
                source_id=row_source_id,
                title=title,
                url=url,
                chunk_metadata=dict(metadata),
                distance=float(row_distance),
            )
            for chunk_id, document_id, row_source_id, title, url, metadata, row_distance in rows
        ]
