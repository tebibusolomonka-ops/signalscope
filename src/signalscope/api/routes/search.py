import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import StringConstraints

from signalscope.api.dependencies import DatabaseSession, EmbeddingProviders
from signalscope.domain.search.embedding_model import MODEL_MAX_LENGTH, PROVIDER_MAX_LENGTH
from signalscope.domain.search.hybrid_service import HybridSearchService
from signalscope.domain.search.repository import MAX_SEARCH_LIMIT
from signalscope.domain.search.schemas import (
    HybridSearchResponse,
    HybridSearchResultRead,
    SearchResponse,
    SearchResultRead,
    SemanticSearchResponse,
    SemanticSearchResultRead,
)
from signalscope.domain.search.semantic_service import SemanticSearchService
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
SemanticQuery = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUERY_LENGTH),
    Query(description="Text to compare with the chunks by meaning."),
]
SearchLimit = Annotated[int, Query(ge=1, le=MAX_SEARCH_LIMIT)]
ProviderName = Annotated[
    str, Query(min_length=1, max_length=PROVIDER_MAX_LENGTH, description="Who runs the model.")
]
ModelName = Annotated[
    str, Query(min_length=1, max_length=MODEL_MAX_LENGTH, description="Embedding model to use.")
]


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


@router.get("/semantic")
async def semantic_search(
    q: SemanticQuery,
    provider: ProviderName,
    model: ModelName,
    session: DatabaseSession,
    providers: EmbeddingProviders,
    limit: SearchLimit = DEFAULT_SEARCH_LIMIT,
    source_id: uuid.UUID | None = None,
) -> SemanticSearchResponse:
    """Find the chunks whose embeddings from model are closest to q, closest first.

    Answers 503 when the provider and model are not configured.
    """
    results = await SemanticSearchService(session, providers).search(
        q, provider=provider, model=model, limit=limit, source_id=source_id
    )
    return SemanticSearchResponse(
        items=[SemanticSearchResultRead.model_validate(result) for result in results]
    )


@router.get("/hybrid")
async def hybrid_search(
    q: SearchQuery,
    provider: ProviderName,
    model: ModelName,
    session: DatabaseSession,
    providers: EmbeddingProviders,
    limit: SearchLimit = DEFAULT_SEARCH_LIMIT,
    source_id: uuid.UUID | None = None,
) -> HybridSearchResponse:
    """Find chunks with full text search and vector search, fused into one ranking.

    Answers 503 when the provider and model are not configured, or when q
    could not be embedded. Chunks without embeddings can still be found by
    full text search.
    """
    results = await HybridSearchService(session, providers).search(
        q, provider=provider, model=model, limit=limit, source_id=source_id
    )
    return HybridSearchResponse(
        items=[HybridSearchResultRead.model_validate(result) for result in results]
    )
