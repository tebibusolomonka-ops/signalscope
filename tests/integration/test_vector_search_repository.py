import hashlib
import math
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.search.vector_repository import VectorSearchRepository, VectorSearchResult
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

PROVIDER = "test"
MODEL = "tiny-2"
QUERY = [1.0, 0.0]


async def create_source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.commit()
    return source


async def create_document(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    *texts: str,
    title: str = "Report",
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
        document = Document(source_id=source.id, title=title, url=f"https://example.test/{title}")
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunks)
        await session.commit()
        return await repository.list_by_document(document.id)


async def embed(
    session_factory: async_sessionmaker[AsyncSession],
    chunk: DocumentChunk,
    vector: list[float],
    **values: Any,
) -> None:
    fields: dict[str, Any] = {
        "chunk_id": chunk.id,
        "provider": PROVIDER,
        "model": MODEL,
        "dimensions": len(vector),
        "chunk_text_hash": chunk.text_hash,
        "embedding": vector,
    }
    async with session_factory() as session:
        session.add(ChunkEmbedding(**(fields | values)))
        await session.commit()


async def search(
    session_factory: async_sessionmaker[AsyncSession],
    vector: list[float] = QUERY,
    limit: int = 10,
    source_id: uuid.UUID | None = None,
) -> list[VectorSearchResult]:
    async with session_factory() as session:
        return await VectorSearchRepository(session).search(
            vector,
            provider=PROVIDER,
            model=MODEL,
            dimensions=len(vector),
            limit=limit,
            source_id=source_id,
        )


async def test_closest_chunks_come_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory)
    far, same, near, opposite = await create_document(
        session_factory, source, "Far.", "Same.", "Near.", "Opposite."
    )
    await embed(session_factory, far, [0.0, 1.0])
    await embed(session_factory, same, [2.0, 0.0])
    await embed(session_factory, near, [1.0, 1.0])
    await embed(session_factory, opposite, [-1.0, 0.0])

    results = await search(session_factory)

    assert [result.chunk_id for result in results] == [same.id, near.id, far.id, opposite.id]
    distances = [result.distance for result in results]
    assert distances == pytest.approx([0.0, 1 - 1 / math.sqrt(2), 1.0, 2.0], abs=1e-6)
    assert results[0].similarity == pytest.approx(1.0)
    assert results[3].similarity == pytest.approx(-1.0)


async def test_result_fields(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory)
    [chunk] = await create_document(session_factory, source, "Only.", title="Budget")
    await embed(session_factory, chunk, [1.0, 0.0])

    [result] = await search(session_factory)

    assert result.chunk_id == chunk.id
    assert result.document_id == chunk.document_id
    assert result.source_id == source.id
    assert (result.title, result.url) == ("Budget", "https://example.test/Budget")
    assert result.chunk_metadata == {"page_number": 1}


async def test_limit(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory)
    chunks = await create_document(session_factory, source, "One.", "Two.", "Three.")
    for chunk in chunks:
        await embed(session_factory, chunk, [1.0, float(chunk.position)])

    results = await search(session_factory, limit=2)

    assert [result.chunk_id for result in results] == [chunks[0].id, chunks[1].id]
    # Hybrid search asks for up to 150 candidates.
    assert len(await search(session_factory, limit=150)) == 3


async def test_equal_distances_keep_document_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory)
    chunks = await create_document(session_factory, source, "One.", "Two.", "Three.")
    for chunk in reversed(chunks):
        await embed(session_factory, chunk, [1.0, 0.0])

    results = await search(session_factory)

    assert [result.chunk_id for result in results] == [chunk.id for chunk in chunks]


async def test_other_providers_and_models_are_ignored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory)
    mine, other_model, other_provider = await create_document(
        session_factory, source, "Mine.", "Other model.", "Other provider."
    )
    await embed(session_factory, mine, [0.0, 1.0])
    await embed(session_factory, other_model, [1.0, 0.0], model="tiny-2b")
    await embed(session_factory, other_provider, [1.0, 0.0], provider="other")

    assert [result.chunk_id for result in await search(session_factory)] == [mine.id]


async def test_vectors_of_other_sizes_are_ignored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory)
    small, large = await create_document(session_factory, source, "Small.", "Large.")
    await embed(session_factory, small, [1.0, 0.0])
    # The same provider and model name with another size must not break the search.
    await embed(session_factory, large, [1.0, 0.0, 0.0])

    assert [result.chunk_id for result in await search(session_factory)] == [small.id]
    assert [result.chunk_id for result in await search(session_factory, [1.0, 0.0, 0.0])] == [
        large.id
    ]


async def test_embeddings_of_older_text_are_ignored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory)
    current, stale = await create_document(session_factory, source, "Current.", "Stale.")
    await embed(session_factory, current, [0.0, 1.0])
    await embed(session_factory, stale, [1.0, 0.0], chunk_text_hash="0" * 64)

    assert [result.chunk_id for result in await search(session_factory)] == [current.id]


async def test_source_filter(session_factory: async_sessionmaker[AsyncSession]) -> None:
    first_source = await create_source(session_factory)
    second_source = await create_source(session_factory)
    [first] = await create_document(session_factory, first_source, "First.")
    [second] = await create_document(session_factory, second_source, "Second.")
    await embed(session_factory, first, [1.0, 0.0])
    await embed(session_factory, second, [1.0, 0.0])

    results = await search(session_factory, source_id=second_source.id)

    assert [result.chunk_id for result in results] == [second.id]


async def test_no_embeddings(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory)
    await create_document(session_factory, source, "Not embedded.")

    assert await search(session_factory) == []


@pytest.mark.parametrize("limit", [0, 151])
async def test_limit_out_of_range(
    session_factory: async_sessionmaker[AsyncSession], limit: int
) -> None:
    with pytest.raises(ValueError, match="limit"):
        await search(session_factory, limit=limit)


async def test_vector_must_match_the_dimensions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(ValueError, match="3 dimensions instead of 2"):
            await VectorSearchRepository(session).search(
                [1.0, 0.0, 0.0], provider=PROVIDER, model=MODEL, dimensions=2, limit=5
            )
