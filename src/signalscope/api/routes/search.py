import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import StringConstraints

from signalscope.api.dependencies import DatabaseSession
from signalscope.domain.search.repository import MAX_SEARCH_LIMIT
from signalscope.domain.search.schemas import SearchResponse, SearchResultRead
from signalscope.domain.search.service import (
    DEFAULT_SEARCH_LIMIT,
    MAX_QUERY_LENGTH,
    SearchService,
)

router = APIRouter(prefix="/search", tags=["Search"])

SearchQuery = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUERY_LENGTH),
    Query(description='Words to find. "Quoted phrases", or and -word work too.'),
]
SearchLimit = Annotated[int, Query(ge=1, le=MAX_SEARCH_LIMIT)]


@router.get("")
async def search(
    q: SearchQuery,
    session: DatabaseSession,
    limit: SearchLimit = DEFAULT_SEARCH_LIMIT,
    source_id: uuid.UUID | None = None,
) -> SearchResponse:
    """Find document chunks that contain the words in q, best match first."""
    results = await SearchService(session).search(q, limit=limit, source_id=source_id)
    return SearchResponse(items=[SearchResultRead.model_validate(result) for result in results])
