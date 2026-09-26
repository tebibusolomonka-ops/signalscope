import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.search.hybrid_service import HybridSearchResult, HybridSearchService
from signalscope.domain.search.repository import MAX_CANDIDATE_LIMIT
from signalscope.domain.search.semantic_service import check_search_request
from signalscope.domain.search.service import DEFAULT_SEARCH_LIMIT
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.reranking.provider import rerank_scores
from signalscope.reranking.registry import RerankerRegistry

# The reranker reorders this many hybrid results per result it returns.
RERANK_CANDIDATE_MULTIPLIER = 3


@dataclass(frozen=True, slots=True)
class RerankedSearchResult:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    source_id: uuid.UUID
    title: str | None
    url: str | None
    # Only set when full text search found the chunk.
    excerpt: str | None
    chunk_metadata: dict[str, Any]
    hybrid_score: float
    # Higher is more relevant. Only comparable within one search.
    reranker_score: float


def rerank_candidate_count(limit: int) -> int:
    return min(limit * RERANK_CANDIDATE_MULTIPLIER, MAX_CANDIDATE_LIMIT)


def order_by_scores(
    candidates: Sequence[HybridSearchResult], scores: Sequence[float], limit: int
) -> list[RerankedSearchResult]:
    """Sort candidates by reranker score, best first.

    Equal scores keep the hybrid order, so the result never depends on chance.
    """
    ranked = sorted(
        zip(candidates, scores, strict=True),
        key=lambda pair: -pair[1],
    )
    return [
        RerankedSearchResult(
            chunk_id=candidate.chunk_id,
            document_id=candidate.document_id,
            source_id=candidate.source_id,
            title=candidate.title,
            url=candidate.url,
            excerpt=candidate.excerpt,
            chunk_metadata=candidate.chunk_metadata,
            hybrid_score=candidate.hybrid_score,
            reranker_score=score,
        )
        for candidate, score in ranked[:limit]
    ]


class RerankedSearchService:
    """Hybrid search, with the candidates reordered by a reranker.

    The reranker reads the full chunk text, not the short excerpt. When the
    reranker is not configured the search fails, instead of quietly returning
    the hybrid order.
    """

    def __init__(
        self,
        session: AsyncSession,
        providers: EmbeddingProviderRegistry,
        rerankers: RerankerRegistry,
    ) -> None:
        self.session = session
        self.hybrid = HybridSearchService(session, providers)
        self.rerankers = rerankers

    async def search(
        self,
        query: str,
        *,
        provider: str,
        model: str,
        reranker_provider: str,
        reranker_model: str,
        limit: int = DEFAULT_SEARCH_LIMIT,
        source_id: uuid.UUID | None = None,
    ) -> list[RerankedSearchResult]:
        query = check_search_request(query, limit)
        # Checked first, so no search runs when there is nothing to rerank with.
        reranker = self.rerankers.get(reranker_provider, reranker_model)
        candidates = await self.hybrid.candidates(
            query,
            provider=provider,
            model=model,
            limit=rerank_candidate_count(limit),
            source_id=source_id,
        )
        texts = await self._chunk_texts([candidate.chunk_id for candidate in candidates])
        scores = await rerank_scores(
            reranker, query, [texts[candidate.chunk_id] for candidate in candidates]
        )
        return order_by_scores(candidates, scores, limit)

    async def _chunk_texts(self, chunk_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not chunk_ids:
            return {}
        rows = await self.session.execute(
            select(DocumentChunk.id, DocumentChunk.text).where(DocumentChunk.id.in_(chunk_ids))
        )
        return {chunk_id: text for chunk_id, text in rows}
