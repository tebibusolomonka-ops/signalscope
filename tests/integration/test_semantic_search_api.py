import hashlib
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_embeddings import FakeEmbeddingProvider
from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.core.settings import Settings
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_repository import ChunkEmbeddingRepository
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

RESULT_FIELDS = {
    "document_id",
    "chunk_id",
    "source_id",
    "title",
    "url",
    "chunk_metadata",
    "similarity",
}


@pytest.fixture
def provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
async def semantic_client(
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
) -> list[uuid.UUID]:
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
        document = Document(source_id=source.id, title="Report", url="https://example.test/r")
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
    return [chunk.id for chunk in saved]


async def test_closest_chunks_come_first(
    semantic_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeEmbeddingProvider,
) -> None:
    energy, water = await add_document(
        session_factory, provider, "Energy prices rise.", "Water levels fall."
    )

    response = await semantic_client.get(
        "/search/semantic", params={"q": "water", "provider": "test", "model": "words-4"}
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["chunk_id"] for item in items] == [str(water), str(energy)]
    assert set(items[0]) == RESULT_FIELDS
    assert items[0]["chunk_metadata"] == {"page_number": 2}
    assert (items[0]["title"], items[0]["url"]) == ("Report", "https://example.test/r")
    assert items[0]["similarity"] == pytest.approx(1.0)
    assert items[0]["similarity"] > items[1]["similarity"]


async def test_limit_and_source_filter(
    semantic_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeEmbeddingProvider,
) -> None:
    await add_document(session_factory, provider, "Water one.", "Water two.")
    [other] = await add_document(session_factory, provider, "Water three.")

    limited = await semantic_client.get(
        "/search/semantic",
        params={"q": "water", "provider": "test", "model": "words-4", "limit": 2},
    )
    assert len(limited.json()["items"]) == 2

    items = (
        await semantic_client.get(
            "/search/semantic",
            params={"q": "water", "provider": "test", "model": "words-4", "limit": 50},
        )
    ).json()["items"]
    source_id = next(item["source_id"] for item in items if item["chunk_id"] == str(other))
    filtered = await semantic_client.get(
        "/search/semantic",
        params={"q": "water", "provider": "test", "model": "words-4", "source_id": source_id},
    )
    assert [item["chunk_id"] for item in filtered.json()["items"]] == [str(other)]


async def test_configured_model_without_embeddings_finds_nothing(
    semantic_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeEmbeddingProvider,
) -> None:
    await add_document(session_factory, provider, "Water.", embed=False)

    response = await semantic_client.get(
        "/search/semantic", params={"q": "water", "provider": "test", "model": "words-4"}
    )

    assert response.status_code == 200
    assert response.json() == {"items": []}


async def test_other_model_is_not_configured(semantic_client: httpx.AsyncClient) -> None:
    response = await semantic_client.get(
        "/search/semantic", params={"q": "water", "provider": "test", "model": "other"}
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


async def test_model_failure_is_reported(
    semantic_client: httpx.AsyncClient, provider: FakeEmbeddingProvider
) -> None:
    provider.error = RuntimeError("private details")

    response = await semantic_client.get(
        "/search/semantic", params={"q": "water", "provider": "test", "model": "words-4"}
    )

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Search query could not be embedded."
