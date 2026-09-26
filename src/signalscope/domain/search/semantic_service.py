import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import InvalidInputError, ServiceUnavailableError, SignalScopeError
from signalscope.domain.search.repository import MAX_SEARCH_LIMIT
from signalscope.domain.search.service import DEFAULT_SEARCH_LIMIT, MAX_QUERY_LENGTH
from signalscope.domain.search.vector_repository import VectorSearchRepository, VectorSearchResult
from signalscope.embeddings.provider import embed
from signalscope.embeddings.registry import EmbeddingProviderRegistry

logger = logging.getLogger(__name__)


class QueryEmbeddingError(ServiceUnavailableError):
    default_message = "Search query could not be embedded."


def check_search_request(query: str, limit: int) -> str:
    """Return the query without surrounding whitespace, or raise InvalidInputError."""
    query = query.strip()
    if not query:
        raise InvalidInputError("Search query must not be empty.")
    if len(query) > MAX_QUERY_LENGTH:
        raise InvalidInputError(f"Search query must be at most {MAX_QUERY_LENGTH} characters.")
    if not 1 <= limit <= MAX_SEARCH_LIMIT:
        raise InvalidInputError(f"Limit must be between 1 and {MAX_SEARCH_LIMIT}.")
    return query


async def embed_query(
    providers: EmbeddingProviderRegistry, query: str, provider_name: str, model_name: str
) -> tuple[list[float], int]:
    """Return the vector of query and its number of dimensions.

    A model that is not configured raises EmbeddingProviderUnavailableError.
    A model that fails raises QueryEmbeddingError.
    """
    provider = providers.get(provider_name, model_name)
    try:
        [vector] = await embed(provider, [query])
    except SignalScopeError as error:
        raise QueryEmbeddingError(f"Search query could not be embedded: {error}") from error
    except Exception as error:
        logger.exception("Embedding model %s/%s failed on a query", provider_name, model_name)
        raise QueryEmbeddingError() from error
    return vector, provider.dimensions


class SemanticSearchService:
    """Finds the chunks whose embeddings are closest to the embedded query."""

    def __init__(self, session: AsyncSession, providers: EmbeddingProviderRegistry) -> None:
        self.repository = VectorSearchRepository(session)
        self.providers = providers

    async def search(
        self,
        query: str,
        *,
        provider: str,
        model: str,
        limit: int = DEFAULT_SEARCH_LIMIT,
        source_id: uuid.UUID | None = None,
    ) -> list[VectorSearchResult]:
        query = check_search_request(query, limit)
        vector, dimensions = await embed_query(self.providers, query, provider, model)
        return await self.repository.search(
            vector,
            provider=provider,
            model=model,
            dimensions=dimensions,
            limit=limit,
            source_id=source_id,
        )
