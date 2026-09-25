import uuid
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import InvalidInputError
from signalscope.domain.search.repository import SearchRepository, SearchResult
from signalscope.domain.search.service import SearchService

pytestmark = pytest.mark.anyio


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Records what reaches the repository, so no database is needed."""
    recorded: list[dict[str, Any]] = []

    async def fake_search(
        self: SearchRepository, query: str, *, limit: int, source_id: uuid.UUID | None = None
    ) -> list[SearchResult]:
        recorded.append({"query": query, "limit": limit, "source_id": source_id})
        return []

    monkeypatch.setattr(SearchRepository, "search", fake_search)
    return recorded


def service() -> SearchService:
    # The session is never used, because the repository is replaced.
    return SearchService(cast(AsyncSession, object()))


async def test_query_is_trimmed_but_not_lowercased(calls: list[dict[str, Any]]) -> None:
    await service().search("  Climate Policy \n")

    assert calls == [{"query": "Climate Policy", "limit": 10, "source_id": None}]


async def test_limit_and_source_are_passed_on(calls: list[dict[str, Any]]) -> None:
    source_id = uuid.uuid4()

    await service().search("climate", limit=50, source_id=source_id)

    assert calls == [{"query": "climate", "limit": 50, "source_id": source_id}]


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
async def test_blank_query_is_rejected_before_any_sql(
    calls: list[dict[str, Any]], query: str
) -> None:
    with pytest.raises(InvalidInputError, match="Search query must not be empty."):
        await service().search(query)

    assert calls == []


async def test_long_query_is_rejected(calls: list[dict[str, Any]]) -> None:
    await service().search("x" * 500)

    with pytest.raises(InvalidInputError, match="at most 500 characters"):
        await service().search("x" * 501)


@pytest.mark.parametrize("limit", [0, -1, 51])
async def test_limit_is_bounded(calls: list[dict[str, Any]], limit: int) -> None:
    with pytest.raises(InvalidInputError, match="Limit must be between 1 and 50."):
        await service().search("climate", limit=limit)

    assert calls == []
