import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import InvalidInputError
from signalscope.domain.search.repository import PUBLIC_SEARCH_LIMIT, SearchRepository, SearchResult

DEFAULT_SEARCH_LIMIT = 10
MAX_QUERY_LENGTH = 500


class SearchService:
    """Checks a search request and runs it."""

    def __init__(self, session: AsyncSession) -> None:
        self.repository = SearchRepository(session)

    async def search(
        self,
        query: str,
        *,
        limit: int = DEFAULT_SEARCH_LIMIT,
        source_id: uuid.UUID | None = None,
    ) -> list[SearchResult]:
        # Only the surrounding whitespace is removed. PostgreSQL handles case.
        query = query.strip()
        if not query:
            raise InvalidInputError("Search query must not be empty.")
        if len(query) > MAX_QUERY_LENGTH:
            raise InvalidInputError(f"Search query must be at most {MAX_QUERY_LENGTH} characters.")
        if not 1 <= limit <= PUBLIC_SEARCH_LIMIT:
            raise InvalidInputError(f"Limit must be between 1 and {PUBLIC_SEARCH_LIMIT}.")
        return await self.repository.search(query, limit=limit, source_id=source_id)
