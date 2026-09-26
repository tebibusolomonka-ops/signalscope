from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ServiceUnavailableError
from signalscope.db.session import get_session
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.storage.blob import BlobStore
from signalscope.storage.local import LocalBlobStore


async def database_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise ServiceUnavailableError("Database is not configured.")
    # aclosing closes the session when the request ends, also when it fails,
    # instead of leaving that to garbage collection.
    async with aclosing(get_session(session_factory)) as sessions:
        async for session in sessions:
            yield session


DatabaseSession = Annotated[AsyncSession, Depends(database_session)]


def blob_store(request: Request) -> BlobStore | None:
    """The store for raw files, or None when SIGNALSCOPE_BLOB_DIR is not set."""
    blob_dir = request.app.state.settings.blob_dir
    return None if blob_dir is None else LocalBlobStore(blob_dir)


Blobs = Annotated[BlobStore | None, Depends(blob_store)]


def embedding_providers(request: Request) -> EmbeddingProviderRegistry:
    registry: EmbeddingProviderRegistry = request.app.state.embedding_providers
    return registry


EmbeddingProviders = Annotated[EmbeddingProviderRegistry, Depends(embedding_providers)]
