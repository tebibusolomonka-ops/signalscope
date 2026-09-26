import hashlib
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

INDEX_NAME = "ix_chunk_embeddings_e5_small_hnsw"
E5 = {"provider": "sentence_transformers", "model": "intfloat/multilingual-e5-small"}


async def index_definition(session_factory: async_sessionmaker[AsyncSession]) -> str:
    async with session_factory() as session:
        definition = await session.scalar(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"), {"name": INDEX_NAME}
        )
    assert definition is not None
    return str(definition)


async def test_index_is_hnsw_with_cosine_ops(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    definition = await index_definition(session_factory)

    assert "ON public.chunk_embeddings USING hnsw" in definition
    assert "((embedding)::vector(384)) vector_cosine_ops" in definition


async def test_index_only_covers_e5_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    definition = await index_definition(session_factory)

    where = definition.split(" WHERE ", 1)[1]
    assert "provider)::text = 'sentence_transformers'::text" in where
    assert "model)::text = 'intfloat/multilingual-e5-small'::text" in where
    assert "dimensions = 384" in where


async def test_index_is_valid_and_uses_the_hnsw_access_method(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT am.amname, i.indisvalid FROM pg_class c "
                    "JOIN pg_am am ON am.oid = c.relam "
                    "JOIN pg_index i ON i.indexrelid = c.oid "
                    "WHERE c.relname = :name"
                ),
                {"name": INDEX_NAME},
            )
        ).one()

    assert tuple(row) == ("hnsw", True)


async def create_chunks(
    session_factory: async_sessionmaker[AsyncSession], count: int
) -> list[DocumentChunk]:
    chunks = [
        TextChunk(
            position=index,
            text=f"Chunk {index}.",
            start_char=0,
            end_char=9,
            text_hash=hashlib.sha256(f"Chunk {index}.".encode()).hexdigest(),
        )
        for index in range(count)
    ]
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id)
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunks)
        await session.commit()
        return await repository.list_by_document(document.id)


def embedding(chunk: DocumentChunk, vector: list[float], **values: Any) -> ChunkEmbedding:
    fields: dict[str, Any] = {
        "chunk_id": chunk.id,
        "dimensions": len(vector),
        "chunk_text_hash": chunk.text_hash,
        "embedding": vector,
    }
    return ChunkEmbedding(**(fields | values))


async def test_vectors_of_any_size_can_still_be_stored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    e5, small, other_384 = await create_chunks(session_factory, 3)

    async with session_factory() as session:
        session.add_all(
            [
                embedding(e5, [0.5] * 384, **E5),
                # Outside the index, so these are never cast to 384 dimensions.
                embedding(small, [1.0, 0.0, 0.0], provider="test", model="tiny-3"),
                embedding(other_384, [0.5] * 384, provider="test", model="other-384"),
            ]
        )
        await session.commit()

    async with session_factory() as session:
        stored = list(await session.scalars(select(ChunkEmbedding.dimensions)))
    assert sorted(stored) == [3, 384, 384]


async def test_e5_name_with_another_size_is_not_indexed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    [chunk] = await create_chunks(session_factory, 1)

    # The dimensions check keeps this row out of the index, so the cast never runs.
    async with session_factory() as session:
        session.add(embedding(chunk, [1.0, 0.0, 0.0], **E5))
        await session.commit()
