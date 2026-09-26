import hashlib
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_embeddings import FakeEmbeddingProvider
from fake_reranker import FakeReranker
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
    "excerpt",
    "chunk_metadata",
    "hybrid_score",
    "reranker_score",
}


@pytest.fixture
def embedder() -> FakeEmbeddingProvider:
    # Stands in for E5 under its name, so the route finds it.
    return FakeEmbeddingProvider("sentence_transformers", "intfloat/multilingual-e5-small")


@pytest.fixture
def reranker() -> FakeReranker:
    return FakeReranker("sentence_transformers", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")


@pytest.fixture
async def client(
    migrated_database: Settings, embedder: FakeEmbeddingProvider, reranker: FakeReranker
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(migrated_database)
    app.state.embedding_providers.register(embedder)
    app.state.rerankers.register(reranker)
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def add_document(
    session_factory: async_sessionmaker[AsyncSession],
    embedder: FakeEmbeddingProvider,
    *texts: str,
) -> list[str]:
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
        for chunk in saved:
            await ChunkEmbeddingRepository(session).save(
                chunk.id,
                embedder.provider_name,
                embedder.model_name,
                chunk.text_hash,
                embedder.vector(chunk.text),
            )
        await session.commit()
    return [str(chunk.id) for chunk in saved]


async def items(client: httpx.AsyncClient, **params: Any) -> list[dict[str, Any]]:
    response = await client.get("/search/reranked", params=params)
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()["items"]
    return found


async def test_results_follow_the_reranker(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    embedder: FakeEmbeddingProvider,
    reranker: FakeReranker,
) -> None:
    once, three_times = await add_document(
        session_factory, embedder, "Water levels.", "Water, water and more water."
    )

    found = await items(client, q="water")

    assert [item["chunk_id"] for item in found] == [three_times, once]
    assert set(found[0]) == RESULT_FIELDS
    assert (found[0]["reranker_score"], found[1]["reranker_score"]) == (3.0, 1.0)
    assert found[0]["chunk_metadata"] == {"page_number": 2}
    assert found[0]["title"] == "Report"
    assert len(reranker.calls) == 1


async def test_limit_and_source_filter(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    embedder: FakeEmbeddingProvider,
) -> None:
    await add_document(session_factory, embedder, "Water one.", "Water two.", "Water three.")
    [other] = await add_document(session_factory, embedder, "Water elsewhere.")

    assert len(await items(client, q="water", limit=2)) == 2
    everything = await items(client, q="water", limit=10)
    source_id = next(item["source_id"] for item in everything if item["chunk_id"] == other)
    filtered = await items(client, q="water", source_id=source_id)
    assert [item["chunk_id"] for item in filtered] == [other]


async def test_reranker_failure_is_a_503(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    embedder: FakeEmbeddingProvider,
    reranker: FakeReranker,
) -> None:
    await add_document(session_factory, embedder, "Water levels.")
    reranker.answer = [float("nan")]

    response = await client.get("/search/reranked", params={"q": "water"})

    assert response.status_code == 503
    assert "not a number" in response.json()["error"]["message"]
