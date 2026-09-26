import hashlib
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.search.vector_repository import (
    VectorSearchRepository,
    VectorSearchResult,
    search_statement,
)
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

PROVIDER = "sentence_transformers"
MODEL = "intfloat/multilingual-e5-small"
DIMENSIONS = 384
INDEX_NAME = "ix_chunk_embeddings_e5_small_hnsw"


def vector(*values: float) -> list[float]:
    """A 384-dimension vector that starts with values and is 0 after them."""
    return [*values, *([0.0] * (DIMENSIONS - len(values)))]


async def create_source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.commit()
    return source


async def add_embedded_chunks(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    vectors: list[list[float]],
    model: str = MODEL,
) -> list[DocumentChunk]:
    chunks = [
        TextChunk(
            position=index,
            text=f"Chunk {index}.",
            start_char=0,
            end_char=9,
            text_hash=hashlib.sha256(f"Chunk {index}.".encode()).hexdigest(),
        )
        for index in range(len(vectors))
    ]
    async with session_factory() as session:
        document = Document(source_id=source.id)
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunks)
        saved = await repository.list_by_document(document.id)
        session.add_all(
            ChunkEmbedding(
                chunk_id=chunk.id,
                provider=PROVIDER,
                model=model,
                dimensions=DIMENSIONS,
                chunk_text_hash=chunk.text_hash,
                embedding=values,
            )
            for chunk, values in zip(saved, vectors, strict=True)
        )
        await session.commit()
    return saved


async def search(
    session_factory: async_sessionmaker[AsyncSession],
    query: list[float],
    limit: int = 10,
    source_id: uuid.UUID | None = None,
    model: str = MODEL,
) -> list[VectorSearchResult]:
    async with session_factory() as session:
        return await VectorSearchRepository(session).search(
            query,
            provider=PROVIDER,
            model=model,
            dimensions=DIMENSIONS,
            limit=limit,
            source_id=source_id,
        )


async def test_nearest_chunks_come_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory)
    same, near, far, opposite = await add_embedded_chunks(
        session_factory,
        source,
        [vector(1.0), vector(1.0, 1.0), vector(0.0, 1.0), vector(-1.0)],
    )

    results = await search(session_factory, vector(1.0))

    assert [result.chunk_id for result in results] == [same.id, near.id, far.id, opposite.id]
    assert [result.distance for result in results] == pytest.approx(
        [0.0, 1 - 0.5**0.5, 1.0, 2.0], abs=1e-6
    )


async def test_index_is_used(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory)
    await add_embedded_chunks(
        session_factory, source, [vector(1.0, float(index)) for index in range(20)]
    )
    statement = search_statement(
        vector(1.0), provider=PROVIDER, model=MODEL, dimensions=DIMENSIONS, limit=5
    )
    sql = str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )

    async with session_factory() as session:
        # With so few rows a sequential scan is cheaper, so rule it out.
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(await session.scalars(text(f"EXPLAIN {sql}")))

    assert f"Index Scan using {INDEX_NAME}" in plan


async def test_more_results_than_the_default_scan_size(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory)
    await add_embedded_chunks(
        session_factory, source, [vector(1.0, float(index)) for index in range(60)]
    )

    results = await search(session_factory, vector(1.0), limit=50)

    # An HNSW scan stops after 40 rows unless it is told to look further.
    assert len(results) == 50
    distances = [result.distance for result in results]
    assert distances == sorted(distances)


async def test_source_filter_still_fills_the_limit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    near_source = await create_source(session_factory)
    far_source = await create_source(session_factory)
    await add_embedded_chunks(
        session_factory, near_source, [vector(1.0, float(index) / 10) for index in range(60)]
    )
    far = await add_embedded_chunks(
        session_factory, far_source, [vector(0.0, 1.0, float(index)) for index in range(5)]
    )

    results = await search(session_factory, vector(1.0), limit=5, source_id=far_source.id)

    # The 60 closer chunks of the other source are filtered out after the scan.
    assert sorted(result.chunk_id for result in results) == sorted(chunk.id for chunk in far)


async def test_other_models_with_384_dimensions_are_kept_apart(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory)
    [e5] = await add_embedded_chunks(session_factory, source, [vector(0.0, 1.0)])
    [other] = await add_embedded_chunks(session_factory, source, [vector(1.0)], model="other")

    assert [result.chunk_id for result in await search(session_factory, vector(1.0))] == [e5.id]
    assert [
        result.chunk_id for result in await search(session_factory, vector(1.0), model="other")
    ] == [other.id]
