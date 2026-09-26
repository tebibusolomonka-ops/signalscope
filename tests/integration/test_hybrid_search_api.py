import hashlib
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_embeddings import FakeEmbeddingProvider
from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.core.settings import Settings
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_repository import ChunkEmbeddingRepository
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

PARAMS = {"provider": "test", "model": "words-4"}
RESULT_FIELDS = {
    "document_id",
    "chunk_id",
    "source_id",
    "title",
    "url",
    "excerpt",
    "chunk_metadata",
    "lexical_rank",
    "vector_similarity",
    "hybrid_score",
}


@pytest.fixture
def provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
async def hybrid_client(
    migrated_database: Settings, provider: FakeEmbeddingProvider
) -> AsyncIterator[httpx.AsyncClient]:
    """An API client whose app has the fake embedding model configured."""
    app = create_app(migrated_database)
    app.state.embedding_providers.register(provider)
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def add_document(
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeEmbeddingProvider,
    *texts: str,
    embed: bool = True,
) -> list[DocumentChunk]:
    chunks = [
        TextChunk(
            position=index,
            text=text,
            start_char=0,
            end_char=len(text),
            text_hash=hashlib.sha256(text.encode()).hexdigest(),
            metadata={"page_number": index + 1},
        )
        for index, text in enumerate(texts)
    ]
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, title="Report")
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunks)
        saved = await repository.list_by_document(document.id)
        if embed:
            for chunk in saved:
                await ChunkEmbeddingRepository(session).save(
                    chunk.id,
                    provider.provider_name,
                    provider.model_name,
                    chunk.text_hash,
                    provider.vector(chunk.text),
                )
        await session.commit()
    return saved


async def items(client: httpx.AsyncClient, **params: Any) -> list[dict[str, Any]]:
    response = await client.get("/search/hybrid", params=PARAMS | params)
    assert response.status_code == 200
    found: list[dict[str, Any]] = response.json()["items"]
    return found


async def test_both_searches_are_combined(
    hybrid_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeEmbeddingProvider,
) -> None:
    reservoir, water, energy = await add_document(
        session_factory,
        provider,
        "The reservoir report.",
        "Water in the reservoir.",
        "Energy prices.",
    )

    found = await items(hybrid_client, q="reservoir water")
    by_chunk = {item["chunk_id"]: item for item in found}

    assert set(found[0]) == RESULT_FIELDS
    assert found[0]["chunk_id"] == str(water.id)
    assert found[0]["lexical_rank"] == 1
    assert "reservoir" in found[0]["excerpt"]
    assert found[0]["vector_similarity"] == pytest.approx(1.0)
    assert found[0]["chunk_metadata"] == {"page_number": 2}
    # Found by vector search only.
    assert by_chunk[str(energy.id)]["lexical_rank"] is None
    assert by_chunk[str(energy.id)]["excerpt"] is None
    assert by_chunk[str(reservoir.id)]["vector_similarity"] is not None
    scores = [item["hybrid_score"] for item in found]
    assert scores == sorted(scores, reverse=True)


async def test_no_embeddings_yet_gives_full_text_results(
    hybrid_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeEmbeddingProvider,
) -> None:
    [chunk] = await add_document(session_factory, provider, "Water report.", embed=False)

    [item] = await items(hybrid_client, q="water")

    assert item["chunk_id"] == str(chunk.id)
    assert (item["lexical_rank"], item["vector_similarity"]) == (1, None)


async def test_limit(
    hybrid_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeEmbeddingProvider,
) -> None:
    await add_document(session_factory, provider, "Water one.", "Water two.", "Water three.")

    assert len(await items(hybrid_client, q="water", limit=2)) == 2


async def test_model_that_is_not_configured(hybrid_client: httpx.AsyncClient) -> None:
    response = await hybrid_client.get(
        "/search/hybrid", params={"q": "water", "provider": "test", "model": "other"}
    )

    assert response.status_code == 503


async def test_query_embedding_failure_is_not_hidden(
    hybrid_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeEmbeddingProvider,
) -> None:
    await add_document(session_factory, provider, "Water report.")
    provider.error = RuntimeError("private details")

    response = await hybrid_client.get("/search/hybrid", params=PARAMS | {"q": "water"})

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Search query could not be embedded."
