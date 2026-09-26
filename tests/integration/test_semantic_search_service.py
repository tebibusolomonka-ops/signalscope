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
from signalscope.domain.search.semantic_service import SemanticSearchService
from signalscope.domain.sources.model import Source, SourceType
from signalscope.embeddings.registry import EmbeddingProviderRegistry

pytestmark = pytest.mark.anyio


@pytest.fixture
def provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


async def add_embedded_document(
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeEmbeddingProvider,
    *texts: str,
    source_id: uuid.UUID | None = None,
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
        if source_id is None:
            source = Source(type=SourceType.UPLOAD, name="Files")
            session.add(source)
            await session.flush()
            source_id = source.id
        document = Document(source_id=source_id, title="Report")
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
    query: str,
    **options: object,
) -> list[uuid.UUID]:
    registry = EmbeddingProviderRegistry()
    registry.register(provider)
    async with session_factory() as session:
        results = await SemanticSearchService(session, registry).search(
            query,
            provider="test",
            model="words-4",
            **options,  # type: ignore[arg-type]
        )
    return [result.chunk_id for result in results]


async def test_closest_chunk_comes_first(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    energy, water, mixed = await add_embedded_document(
        session_factory,
        provider,
        "Energy prices and energy use.",
        "Water supply and water quality.",
        "Energy for water pumps.",
    )

    assert await search(session_factory, provider, "water water water") == [
        water.id,
        mixed.id,
        energy.id,
    ]
    assert provider.calls == [["water water water"]]


async def test_limit(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    await add_embedded_document(session_factory, provider, "Water.", "Energy.", "Climate.")

    assert len(await search(session_factory, provider, "water", limit=2)) == 2


async def test_source_filter(
    session_factory: async_sessionmaker[AsyncSession], provider: FakeEmbeddingProvider
) -> None:
    await add_embedded_document(session_factory, provider, "Water here.")
    [other] = await add_embedded_document(session_factory, provider, "Water there.")
    async with session_factory() as session:
        document = await session.get(Document, other.document_id)
    assert document is not None

    assert await search(session_factory, provider, "water", source_id=document.source_id) == [
        other.id
    ]
