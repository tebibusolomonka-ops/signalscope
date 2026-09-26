import uuid
from collections.abc import Sequence
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fake_embeddings import FakeEmbeddingProvider
from signalscope.core.errors import InvalidInputError
from signalscope.domain.search.hybrid_service import (
    RRF_CONSTANT,
    HybridSearchService,
    candidate_count,
    fuse,
)
from signalscope.domain.search.repository import SearchResult
from signalscope.domain.search.semantic_service import QueryEmbeddingError
from signalscope.domain.search.vector_repository import VectorSearchResult
from signalscope.embeddings.registry import (
    EmbeddingProviderRegistry,
    EmbeddingProviderUnavailableError,
)

pytestmark = pytest.mark.anyio

DOCUMENT_ID = uuid.uuid4()
SOURCE_ID = uuid.uuid4()
# Sorted, so ties broken by chunk ID are easy to predict.
A, B, C, D = sorted(uuid.uuid4() for _ in range(4))


def lexical(chunk_id: uuid.UUID) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        document_id=DOCUMENT_ID,
        source_id=SOURCE_ID,
        title="Report",
        url=None,
        excerpt=f"Excerpt of {chunk_id}",
        rank=0.5,
        chunk_metadata={"page_number": 1},
    )


def vector(chunk_id: uuid.UUID, distance: float = 0.25) -> VectorSearchResult:
    return VectorSearchResult(
        chunk_id=chunk_id,
        document_id=DOCUMENT_ID,
        source_id=SOURCE_ID,
        title="Report",
        url=None,
        chunk_metadata={"page_number": 1},
        distance=distance,
    )


def score(*places: int) -> float:
    return sum(1 / (RRF_CONSTANT + place) for place in places)


def test_chunk_found_only_by_full_text() -> None:
    [result] = fuse([lexical(A)], [], limit=10)

    assert result.chunk_id == A
    assert (result.lexical_rank, result.vector_similarity) == (1, None)
    assert result.excerpt == f"Excerpt of {A}"
    assert result.chunk_metadata == {"page_number": 1}
    assert result.hybrid_score == pytest.approx(score(1))


def test_chunk_found_only_by_vectors() -> None:
    [result] = fuse([], [vector(A, distance=0.25)], limit=10)

    assert (result.lexical_rank, result.excerpt) == (None, None)
    assert result.vector_similarity == pytest.approx(0.75)
    assert result.hybrid_score == pytest.approx(score(1))


def test_chunk_found_by_both_is_listed_once() -> None:
    [result] = fuse([lexical(A)], [vector(A)], limit=10)

    assert result.lexical_rank == 1
    assert result.vector_similarity == pytest.approx(0.75)
    assert result.excerpt is not None
    assert result.hybrid_score == pytest.approx(score(1, 1))


def test_reciprocal_rank_fusion_order() -> None:
    results = fuse(
        [lexical(A), lexical(B), lexical(C)],
        [vector(C), vector(D), vector(B)],
        limit=10,
    )

    # C: places 3 and 1. B: places 2 and 3. A: place 1. D: place 2.
    assert [result.chunk_id for result in results] == [C, B, A, D]
    assert [result.hybrid_score for result in results] == pytest.approx(
        [score(3, 1), score(2, 3), score(1), score(2)]
    )


def test_equal_scores_prefer_the_better_place_then_the_id() -> None:
    results = fuse([lexical(B), lexical(D)], [vector(C), vector(A)], limit=10)

    # B and C both have place 1, D and A both have place 2.
    assert [result.chunk_id for result in results] == [B, C, A, D]


def test_limit() -> None:
    results = fuse([lexical(A), lexical(B)], [vector(C), vector(D)], limit=3)

    assert len(results) == 3


@pytest.mark.parametrize(("limit", "expected"), [(1, 3), (10, 30), (17, 50), (50, 50)])
def test_candidate_count(limit: int, expected: int) -> None:
    assert candidate_count(limit) == expected


class FakeLexical:
    def __init__(self, results: list[SearchResult]) -> None:
        self.results = results
        self.calls: list[dict[str, Any]] = []

    async def search(self, query: str, **options: Any) -> list[SearchResult]:
        self.calls.append({"query": query, **options})
        return self.results


class FakeVectors:
    def __init__(self, results: list[VectorSearchResult]) -> None:
        self.results = results
        self.calls: list[dict[str, Any]] = []

    async def search(self, vector: Sequence[float], **options: Any) -> list[VectorSearchResult]:
        self.calls.append({"vector": list(vector), **options})
        return self.results


def service_with(
    provider: FakeEmbeddingProvider,
    lexical_results: list[SearchResult],
    vector_results: list[VectorSearchResult],
) -> tuple[HybridSearchService, FakeLexical, FakeVectors]:
    registry = EmbeddingProviderRegistry()
    registry.register(provider)
    service = HybridSearchService(cast(AsyncSession, None), registry)
    fake_lexical = FakeLexical(lexical_results)
    fake_vectors = FakeVectors(vector_results)
    service.lexical = fake_lexical  # type: ignore[assignment]
    service.vectors = fake_vectors  # type: ignore[assignment]
    return service, fake_lexical, fake_vectors


async def test_service_runs_both_searches() -> None:
    provider = FakeEmbeddingProvider()
    service, fake_lexical, fake_vectors = service_with(provider, [lexical(A)], [vector(B)])
    source_id = uuid.uuid4()

    results = await service.search(
        " water ", provider="test", model="words-4", limit=2, source_id=source_id
    )

    assert [result.chunk_id for result in results] == [A, B]
    assert provider.calls == [["water"]]
    assert fake_lexical.calls == [{"query": "water", "limit": 6, "source_id": source_id}]
    assert fake_vectors.calls == [
        {
            "vector": [0.0, 0.0, 1.0, 1.0],
            "provider": "test",
            "model": "words-4",
            "dimensions": 4,
            "limit": 6,
            "source_id": source_id,
        }
    ]


async def test_no_embeddings_gives_full_text_results() -> None:
    service, _, _ = service_with(FakeEmbeddingProvider(), [lexical(A)], [])

    [result] = await service.search("water", provider="test", model="words-4")

    assert (result.chunk_id, result.vector_similarity) == (A, None)


async def test_blank_query_is_rejected_before_the_model_runs() -> None:
    provider = FakeEmbeddingProvider()
    service, fake_lexical, _ = service_with(provider, [], [])

    with pytest.raises(InvalidInputError):
        await service.search("  ", provider="test", model="words-4")

    assert provider.calls == []
    assert fake_lexical.calls == []


async def test_model_that_is_not_configured() -> None:
    service, fake_lexical, _ = service_with(FakeEmbeddingProvider(), [lexical(A)], [])

    with pytest.raises(EmbeddingProviderUnavailableError):
        await service.search("water", provider="test", model="other")

    assert fake_lexical.calls == []


async def test_model_failure_is_not_hidden() -> None:
    provider = FakeEmbeddingProvider()
    provider.error = RuntimeError("private details")
    service, fake_lexical, _ = service_with(provider, [lexical(A)], [])

    with pytest.raises(QueryEmbeddingError):
        await service.search("water", provider="test", model="words-4")

    assert fake_lexical.calls == []
