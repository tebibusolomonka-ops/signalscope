import uuid
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import InvalidInputError
from signalscope.domain.search.hybrid_service import HybridSearchResult
from signalscope.domain.search.reranked_service import (
    RerankedSearchService,
    order_by_scores,
    rerank_candidate_count,
)
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.reranking.provider import RerankerUnavailableError
from signalscope.reranking.registry import RerankerRegistry

pytestmark = pytest.mark.anyio


def candidate(score: float) -> HybridSearchResult:
    return HybridSearchResult(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        title="Report",
        url="https://example.test/r",
        chunk_metadata={"page_number": 2},
        excerpt="An excerpt.",
        lexical_rank=1,
        vector_similarity=0.5,
        hybrid_score=score,
    )


@pytest.mark.parametrize(("limit", "expected"), [(1, 3), (10, 30), (50, 150)])
def test_candidate_count(limit: int, expected: int) -> None:
    assert rerank_candidate_count(limit) == expected


def test_order_by_reranker_score() -> None:
    first, second, third = candidate(0.03), candidate(0.02), candidate(0.01)

    results = order_by_scores([first, second, third], [0.1, 0.9, 0.5], limit=3)

    assert [result.chunk_id for result in results] == [
        second.chunk_id,
        third.chunk_id,
        first.chunk_id,
    ]
    assert [result.reranker_score for result in results] == [0.9, 0.5, 0.1]
    assert results[0].hybrid_score == 0.02


def test_equal_scores_keep_the_hybrid_order() -> None:
    candidates = [candidate(0.03), candidate(0.02), candidate(0.01)]

    results = order_by_scores(candidates, [0.5, 0.5, 0.5], limit=3)

    assert [result.chunk_id for result in results] == [item.chunk_id for item in candidates]


def test_limit_and_metadata() -> None:
    candidates = [candidate(0.03), candidate(0.02)]

    [result] = order_by_scores(candidates, [1.0, 2.0], limit=1)

    source = candidates[1]
    assert (result.document_id, result.source_id, result.title, result.url) == (
        source.document_id,
        source.source_id,
        "Report",
        "https://example.test/r",
    )
    assert (result.excerpt, result.chunk_metadata) == ("An excerpt.", {"page_number": 2})


def service() -> RerankedSearchService:
    # Both registries are empty, and no step reaches the session.
    return RerankedSearchService(
        cast(AsyncSession, None), EmbeddingProviderRegistry(), RerankerRegistry()
    )


async def test_missing_reranker_fails_before_searching() -> None:
    with pytest.raises(RerankerUnavailableError, match="test/word-count is not configured"):
        await service().search(
            "wind",
            provider="test",
            model="words-4",
            reranker_provider="test",
            reranker_model="word-count",
        )


@pytest.mark.parametrize(("query", "limit"), [(" ", 10), ("wind", 0), ("wind", 51)])
async def test_bad_requests_are_rejected_first(query: str, limit: int) -> None:
    with pytest.raises(InvalidInputError):
        await service().search(
            query,
            provider="test",
            model="words-4",
            reranker_provider="test",
            reranker_model="word-count",
            limit=limit,
        )
