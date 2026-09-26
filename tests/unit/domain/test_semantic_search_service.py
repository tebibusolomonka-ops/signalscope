import uuid
from collections.abc import Sequence
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fake_embeddings import FakeEmbeddingProvider
from signalscope.core.errors import InvalidInputError
from signalscope.domain.search.semantic_service import QueryEmbeddingError, SemanticSearchService
from signalscope.domain.search.vector_repository import VectorSearchResult
from signalscope.embeddings.provider import EmbeddingError, EmbeddingInputRole
from signalscope.embeddings.registry import (
    EmbeddingProviderRegistry,
    EmbeddingProviderUnavailableError,
)

pytestmark = pytest.mark.anyio


class FakeRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def search(self, vector: Sequence[float], **options: Any) -> list[VectorSearchResult]:
        self.calls.append({"vector": list(vector), **options})
        return []


@pytest.fixture
def provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def service(provider: FakeEmbeddingProvider, repository: FakeRepository) -> SemanticSearchService:
    registry = EmbeddingProviderRegistry()
    registry.register(provider)
    # The fake repository never touches the session.
    service = SemanticSearchService(cast(AsyncSession, None), registry)
    service.repository = repository  # type: ignore[assignment]
    return service


async def test_query_is_embedded_once_and_searched(
    service: SemanticSearchService, provider: FakeEmbeddingProvider, repository: FakeRepository
) -> None:
    source_id = uuid.uuid4()

    await service.search(
        "  Water and energy  ", provider="test", model="words-4", limit=7, source_id=source_id
    )

    assert provider.calls == [["Water and energy"]]
    assert provider.roles == [EmbeddingInputRole.QUERY]
    assert repository.calls == [
        {
            "vector": [0.0, 1.0, 1.0, 1.0],
            "provider": "test",
            "model": "words-4",
            "dimensions": 4,
            "limit": 7,
            "source_id": source_id,
        }
    ]


async def test_default_limit_and_no_source(
    service: SemanticSearchService, repository: FakeRepository
) -> None:
    await service.search("water", provider="test", model="words-4")

    assert (repository.calls[0]["limit"], repository.calls[0]["source_id"]) == (10, None)


@pytest.mark.parametrize(
    ("query", "limit", "message"),
    [
        ("", 10, "must not be empty"),
        ("   ", 10, "must not be empty"),
        ("x" * 501, 10, "at most 500 characters"),
        ("water", 0, "between 1 and 50"),
        ("water", 51, "between 1 and 50"),
    ],
    ids=["empty", "blank", "too long", "limit too small", "limit too large"],
)
async def test_bad_requests_are_rejected_before_the_model_runs(
    service: SemanticSearchService,
    provider: FakeEmbeddingProvider,
    query: str,
    limit: int,
    message: str,
) -> None:
    with pytest.raises(InvalidInputError, match=message):
        await service.search(query, provider="test", model="words-4", limit=limit)

    assert provider.calls == []


async def test_model_that_is_not_configured(
    service: SemanticSearchService, repository: FakeRepository
) -> None:
    with pytest.raises(EmbeddingProviderUnavailableError, match="test/other is not configured"):
        await service.search("water", provider="test", model="other")

    assert repository.calls == []


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (EmbeddingError("Model is not ready."), "could not be embedded: Model is not ready."),
        (RuntimeError("private details"), "^Search query could not be embedded.$"),
    ],
    ids=["expected error", "unexpected error"],
)
async def test_model_failure(
    service: SemanticSearchService,
    provider: FakeEmbeddingProvider,
    repository: FakeRepository,
    error: Exception,
    message: str,
) -> None:
    provider.error = error

    with pytest.raises(QueryEmbeddingError, match=message):
        await service.search("water", provider="test", model="words-4")

    assert repository.calls == []


async def test_bad_vector_from_the_model(
    service: SemanticSearchService, provider: FakeEmbeddingProvider, repository: FakeRepository
) -> None:
    provider.answer = [[1.0, 2.0]]

    with pytest.raises(QueryEmbeddingError, match="2 dimensions instead of 4"):
        await service.search("water", provider="test", model="words-4")

    assert repository.calls == []
