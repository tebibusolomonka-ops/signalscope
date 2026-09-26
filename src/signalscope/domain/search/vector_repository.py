import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ColumnElement, Select, cast, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.search.repository import MAX_CANDIDATE_LIMIT
from signalscope.embeddings.models import MULTILINGUAL_E5_SMALL

# The pgvector default for how many rows an HNSW scan looks at.
DEFAULT_EF_SEARCH = 40


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
    """Nearest neighbour search over chunk embeddings with pgvector.

    Vectors from different models cannot be compared, so only embeddings from
    one provider and model, with the query's number of dimensions, are
    searched. Embeddings made from older chunk text are left out.

    The local E5 model has an HNSW index, which makes its search approximate
    and fast. Every other model is searched exactly, by comparing every
    matching embedding.
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
        statement = search_statement(
            vector,
            provider=provider,
            model=model,
            dimensions=dimensions,
            limit=limit,
            source_id=source_id,
        )
        if uses_e5_index(provider, model, dimensions):
            await self._configure_index_scan(limit)
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

    async def _configure_index_scan(self, limit: int) -> None:
        """Let the HNSW scan return enough rows, until the transaction ends.

        By default a scan stops after hnsw.ef_search rows, before filters such
        as the source run. An iterative scan keeps going until the query has
        its rows, and strict order keeps them sorted by distance.
        """
        await self.session.execute(
            text(
                "SELECT set_config('hnsw.ef_search', :ef_search, true), "
                "set_config('hnsw.iterative_scan', 'strict_order', true)"
            ),
            {"ef_search": str(max(DEFAULT_EF_SEARCH, limit))},
        )


def uses_e5_index(provider: str, model: str, dimensions: int) -> bool:
    spec = MULTILINGUAL_E5_SMALL
    return (provider, model, dimensions) == (spec.provider, spec.model, spec.dimensions)


def search_statement(
    vector: Sequence[float],
    *,
    provider: str,
    model: str,
    dimensions: int,
    limit: int,
    source_id: uuid.UUID | None = None,
) -> Select[tuple[uuid.UUID, uuid.UUID, uuid.UUID, str | None, str | None, Any, float]]:
    if not 1 <= limit <= MAX_CANDIDATE_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_CANDIDATE_LIMIT}")
    if len(vector) != dimensions:
        raise ValueError(f"vector has {len(vector)} dimensions instead of {dimensions}")
    if uses_e5_index(provider, model, dimensions):
        # The same expression and filters as the partial index, so PostgreSQL can
        # use it. The filters are written into the SQL, because the planner can
        # only match the index WHERE clause against fixed values.
        stored: ColumnElement[Any] = cast(ChunkEmbedding.embedding, Vector(dimensions))
        filters = [
            ChunkEmbedding.provider == literal(provider, literal_execute=True),
            ChunkEmbedding.model == literal(model, literal_execute=True),
            ChunkEmbedding.dimensions == literal(dimensions, literal_execute=True),
        ]
    else:
        stored = ChunkEmbedding.embedding.expression
        filters = [
            ChunkEmbedding.provider == provider,
            ChunkEmbedding.model == model,
            ChunkEmbedding.dimensions == dimensions,
        ]
    distance = stored.cosine_distance(list(vector))
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
        .where(*filters, ChunkEmbedding.chunk_text_hash == DocumentChunk.text_hash)
        # Chunks at the same distance keep the order they have in their documents.
        .order_by(distance, DocumentChunk.document_id, DocumentChunk.position)
        .limit(limit)
    )
    if source_id is not None:
        statement = statement.where(Document.source_id == source_id)
    return statement
