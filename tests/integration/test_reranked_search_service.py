import hashlib
import uuid
from collections.abc import Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_embeddings import FakeEmbeddingProvider
from fake_reranker import FakeReranker
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_repository import ChunkEmbeddingRepository
from signalscope.domain.search.hybrid_service import HybridSearchService
from signalscope.domain.search.reranked_service import RerankedSearchResult, RerankedSearchService
from signalscope.domain.sources.model import Source, SourceType
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.reranking.registry import RerankerRegistry

pytestmark = pytest.mark.anyio


async def add_document(
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeEmbeddingProvider,
    *texts: str,
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
        document = Document(source_id=source.id, title="Report", url="https://example.test/r")
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunks)
        saved = await repository.list_by_document(document.id)
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


async def search(
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeEmbeddingProvider,
    reranker: FakeReranker,
    query: str,
    limit: int = 10,
    source_id: uuid.UUID | None = None,
) -> list[RerankedSearchResult]:
    providers = EmbeddingProviderRegistry()
    providers.register(provider)
    rerankers = RerankerRegistry()
    rerankers.register(reranker)
    async with session_factory() as session:
        return await RerankedSearchService(session, providers, rerankers).search(
            query,
            provider="test",
            model="words-4",
            reranker_provider="test",
            reranker_model="word-count",
            limit=limit,
            source_id=source_id,
        )


class ReversingReranker(FakeReranker):
    """Gives later candidates higher scores, so it reverses the hybrid order."""

    async def score(self, query: str, passages: Sequence[str]) -> list[float]:
        self.calls.append((query, list(passages)))
        return [float(index) for index in range(len(passages))]


async def test_reranker_decides_the_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeEmbeddingProvider()
    await add_document(session_factory, provider, "Water.", "Water and energy.", "Water water.")
    providers = EmbeddingProviderRegistry()
    providers.register(provider)
    async with session_factory() as session:
        hybrid = await HybridSearchService(session, providers).search(
            "water", provider="test", model="words-4", limit=3
        )

    results = await search(session_factory, provider, ReversingReranker(), "water", limit=3)

    assert len(hybrid) == 3
    assert [result.chunk_id for result in results] == [
        result.chunk_id for result in reversed(hybrid)
    ]
    assert [result.reranker_score for result in results] == [2.0, 1.0, 0.0]
    assert [result.hybrid_score for result in results] == [
        result.hybrid_score for result in reversed(hybrid)
    ]


async def test_reranker_reads_the_full_chunk_text(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider, reranker = FakeEmbeddingProvider(), FakeReranker()
    long_text = "Water levels. " + "More notes about the harbour. " * 30
    [chunk] = await add_document(session_factory, provider, long_text)

    await search(session_factory, provider, reranker, "water")

    assert reranker.calls == [("water", [long_text])]
    assert chunk.text == long_text


async def test_candidate_count_and_limit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider, reranker = FakeEmbeddingProvider(), FakeReranker()
    await add_document(session_factory, provider, *(f"Water note {index}." for index in range(8)))

    results = await search(session_factory, provider, reranker, "water", limit=2)

    assert len(results) == 2
    # Three candidates per result, from one reranker call.
    [(_, passages)] = reranker.calls
    assert len(passages) == 6


async def test_metadata_is_kept(session_factory: async_sessionmaker[AsyncSession]) -> None:
    provider, reranker = FakeEmbeddingProvider(), FakeReranker()
    [chunk] = await add_document(session_factory, provider, "Water levels fell.")

    [result] = await search(session_factory, provider, reranker, "water")

    assert (result.chunk_id, result.document_id) == (chunk.id, chunk.document_id)
    assert (result.title, result.url) == ("Report", "https://example.test/r")
    assert result.chunk_metadata == {"page_number": 1}
    assert result.excerpt is not None and "Water" in result.excerpt


async def test_source_filter(session_factory: async_sessionmaker[AsyncSession]) -> None:
    provider, reranker = FakeEmbeddingProvider(), FakeReranker()
    await add_document(session_factory, provider, "Water here, water here.")
    [other] = await add_document(session_factory, provider, "Water there.")
    async with session_factory() as session:
        document = await session.get(Document, other.document_id)
        assert document is not None
        source_id = document.source_id

    results = await search(session_factory, provider, reranker, "water", source_id=source_id)

    assert [result.chunk_id for result in results] == [other.id]


async def test_nothing_found_skips_the_reranker(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider, reranker = FakeEmbeddingProvider(), FakeReranker()

    assert await search(session_factory, provider, reranker, "water") == []
    assert reranker.calls == []
