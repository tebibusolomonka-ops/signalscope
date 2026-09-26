import hashlib
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_embeddings import FakeEmbeddingProvider
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_repository import ChunkEmbeddingRepository
from signalscope.domain.search.hybrid_service import HybridSearchResult, HybridSearchService
from signalscope.domain.sources.model import Source, SourceType
from signalscope.embeddings.registry import EmbeddingProviderRegistry

pytestmark = pytest.mark.anyio


@pytest.fixture
def provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


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


async def search(
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeEmbeddingProvider,
    query: str,
    **options: object,
) -> list[HybridSearchResult]:
    registry = EmbeddingProviderRegistry()
    registry.register(provider)
    async with session_factory() as session:
        return await HybridSearchService(session, registry).search(
            query,
            provider="test",
            model="words-4",
            **options,  # type: ignore[arg-type]
        )


async def test_both_searches_are_combined(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    # "reservoir" is not a word the fake model counts, so only full text finds it.
    reservoir, water, energy = await add_document(
        session_factory,
        provider,
        "The reservoir report.",
        "Water in the reservoir.",
        "Energy prices.",
    )

    results = await search(session_factory, provider, "reservoir water")
    by_chunk = {result.chunk_id: result for result in results}

    # Only the chunk with both words matches the full text query.
    assert by_chunk[water.id].lexical_rank == 1
    assert by_chunk[water.id].excerpt is not None
    assert by_chunk[water.id].vector_similarity is not None
    assert results[0].chunk_id == water.id
    assert by_chunk[energy.id].lexical_rank is None
    assert by_chunk[reservoir.id].vector_similarity is not None
    assert len(results) == len(by_chunk) == 3


async def test_chunks_without_embeddings_come_from_full_text(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    [chunk] = await add_document(session_factory, provider, "Water report.", embed=False)

    [result] = await search(session_factory, provider, "water")

    assert result.chunk_id == chunk.id
    assert (result.lexical_rank, result.vector_similarity) == (1, None)


async def test_source_filter_and_limit(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    await add_document(session_factory, provider, "Water one.", "Water two.")
    [other] = await add_document(session_factory, provider, "Water three.")
    async with session_factory() as session:
        document = await session.get(Document, other.document_id)
    assert document is not None

    filtered = await search(session_factory, provider, "water", source_id=document.source_id)
    limited = await search(session_factory, provider, "water", limit=2)

    assert [result.chunk_id for result in filtered] == [other.id]
    assert len(limited) == 2


async def test_nothing_found(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    assert await search(session_factory, provider, "water", source_id=uuid.uuid4()) == []
