import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.search.repository import MAX_CANDIDATE_LIMIT, SearchRepository, SearchResult
from signalscope.domain.search.semantic_service import check_search_request, embed_query
from signalscope.domain.search.service import DEFAULT_SEARCH_LIMIT
from signalscope.domain.search.vector_repository import VectorSearchRepository, VectorSearchResult
from signalscope.embeddings.registry import EmbeddingProviderRegistry

# Each search returns this many times the requested results, so a chunk that
# only one of them ranks high can still make it into the fused list.
CANDIDATE_MULTIPLIER = 3
# Enough for three candidates per result at the largest public limit.
MAX_HYBRID_CANDIDATES = MAX_CANDIDATE_LIMIT
# The usual constant for Reciprocal Rank Fusion. It keeps the top few ranks
# from outweighing everything else.
RRF_CONSTANT = 60


@dataclass(frozen=True, slots=True)
class HybridSearchResult:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    source_id: uuid.UUID
    title: str | None
    url: str | None
    chunk_metadata: dict[str, Any]
    # Only set when the full text search found the chunk.
    excerpt: str | None
    # The 1-based place in the full text results, when the chunk is there.
    lexical_rank: int | None
    # 1 minus the cosine distance, when the vector search found the chunk.
    vector_similarity: float | None
    hybrid_score: float


def candidate_count(limit: int) -> int:
    return min(limit * CANDIDATE_MULTIPLIER, MAX_HYBRID_CANDIDATES)


def fuse(
    lexical: list[SearchResult], vector: list[VectorSearchResult], limit: int
) -> list[HybridSearchResult]:
    """Merge two ranked lists with Reciprocal Rank Fusion.

    A chunk scores 1 / (RRF_CONSTANT + place) for each list it is in. Only the
    places are used, because full text ranks and cosine distances are on
    different scales and cannot be added.
    """
    lexical_places = {result.chunk_id: place for place, result in enumerate(lexical, start=1)}
    vector_places = {result.chunk_id: place for place, result in enumerate(vector, start=1)}
    found: dict[uuid.UUID, SearchResult | VectorSearchResult] = {}
    for hit in lexical:
        found.setdefault(hit.chunk_id, hit)
    for nearest in vector:
        found.setdefault(nearest.chunk_id, nearest)
    excerpts = {hit.chunk_id: hit.excerpt for hit in lexical}
    similarities = {nearest.chunk_id: nearest.similarity for nearest in vector}

    ranked: list[tuple[float, int, uuid.UUID, HybridSearchResult]] = []
    for chunk_id, result in found.items():
        places = [
            place
            for place in (lexical_places.get(chunk_id), vector_places.get(chunk_id))
            if place is not None
        ]
        score = sum(1 / (RRF_CONSTANT + place) for place in places)
        fused = HybridSearchResult(
            chunk_id=chunk_id,
            document_id=result.document_id,
            source_id=result.source_id,
            title=result.title,
            url=result.url,
            chunk_metadata=result.chunk_metadata,
            excerpt=excerpts.get(chunk_id),
            lexical_rank=lexical_places.get(chunk_id),
            vector_similarity=similarities.get(chunk_id),
            hybrid_score=score,
        )
        # Equal scores go to the chunk with the best single place, then by ID,
        # so the order never depends on chance.
        ranked.append((-score, min(places), chunk_id, fused))
    ranked.sort(key=lambda entry: entry[:3])
    return [entry[3] for entry in ranked[:limit]]


class HybridSearchService:
    """Combines full text search and vector search into one ranked list.

    The query must be embedded. When that fails the error is raised, instead
    of quietly returning full text results only. A configured model with no
    embeddings yet still gives the full text results.
    """

    def __init__(self, session: AsyncSession, providers: EmbeddingProviderRegistry) -> None:
        self.lexical = SearchRepository(session)
        self.vectors = VectorSearchRepository(session)
        self.providers = providers

    async def search(
        self,
        query: str,
        *,
        provider: str,
        model: str,
        limit: int = DEFAULT_SEARCH_LIMIT,
        source_id: uuid.UUID | None = None,
    ) -> list[HybridSearchResult]:
        query = check_search_request(query, limit)
        vector, dimensions = await embed_query(self.providers, query, provider, model)
        candidates = candidate_count(limit)
        lexical = await self.lexical.search(query, limit=candidates, source_id=source_id)
        nearest = await self.vectors.search(
            vector,
            provider=provider,
            model=model,
            dimensions=dimensions,
            limit=candidates,
            source_id=source_id,
        )
        return fuse(lexical, nearest, limit)
