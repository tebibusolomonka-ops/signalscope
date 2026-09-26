import hashlib
import uuid
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import chunk_text
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

TEXT = "Climate policy for coastal cities."
TEXT_HASH = hashlib.sha256(TEXT.encode()).hexdigest()
# Whole and half numbers survive the float4 storage exactly.
VECTOR = [1.0, -0.5, 2.25]


async def create_chunk(session_factory: async_sessionmaker[AsyncSession]) -> DocumentChunk:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, content=TEXT)
        session.add(document)
        await session.flush()
        await DocumentChunkRepository(session).replace_for_document(document.id, chunk_text(TEXT))
        await session.commit()
        [chunk] = await DocumentChunkRepository(session).list_by_document(document.id)
    return chunk


def embedding_for(chunk: DocumentChunk, **values: Any) -> ChunkEmbedding:
    fields: dict[str, Any] = {
        "chunk_id": chunk.id,
        "provider": "test",
        "model": "tiny-3",
        "dimensions": len(VECTOR),
        "chunk_text_hash": TEXT_HASH,
        "embedding": VECTOR,
    }
    return ChunkEmbedding(**(fields | values))


async def add(
    session_factory: async_sessionmaker[AsyncSession], *embeddings: ChunkEmbedding
) -> None:
    async with session_factory() as session:
        session.add_all(embeddings)
        await session.commit()


async def stored(session_factory: async_sessionmaker[AsyncSession]) -> list[ChunkEmbedding]:
    async with session_factory() as session:
        return list(await session.scalars(select(ChunkEmbedding)))


async def test_vector_is_stored_and_read_back(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk = await create_chunk(session_factory)

    await add(session_factory, embedding_for(chunk))

    [saved] = await stored(session_factory)
    assert saved.embedding == VECTOR
    assert (saved.provider, saved.model, saved.dimensions) == ("test", "tiny-3", 3)
    assert saved.chunk_text_hash == TEXT_HASH
    assert saved.created_at is not None


async def test_longer_vectors_are_allowed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk = await create_chunk(session_factory)
    vector = [float(number) for number in range(384)]

    await add(session_factory, embedding_for(chunk, dimensions=384, embedding=vector))

    [saved] = await stored(session_factory)
    assert saved.embedding == vector


async def test_one_embedding_per_provider_and_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk = await create_chunk(session_factory)
    await add(session_factory, embedding_for(chunk))

    async with session_factory() as session:
        session.add(embedding_for(chunk))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_other_models_can_embed_the_same_chunk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk = await create_chunk(session_factory)

    await add(
        session_factory,
        embedding_for(chunk),
        embedding_for(chunk, model="tiny-4"),
        embedding_for(chunk, provider="other"),
    )

    assert len(await stored(session_factory)) == 3


@pytest.mark.parametrize(
    "values",
    [
        {"dimensions": 0},
        {"dimensions": -1},
        {"chunk_text_hash": "abc"},
        {"chunk_text_hash": TEXT_HASH.upper()},
    ],
)
async def test_invalid_embedding_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, Any]
) -> None:
    chunk = await create_chunk(session_factory)

    async with session_factory() as session:
        session.add(embedding_for(chunk, **values))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_unknown_chunk_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk = await create_chunk(session_factory)

    async with session_factory() as session:
        session.add(embedding_for(chunk, chunk_id=uuid.uuid4()))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_embeddings_go_away_with_their_chunk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk = await create_chunk(session_factory)
    await add(session_factory, embedding_for(chunk))

    async with session_factory() as session:
        await session.execute(delete(DocumentChunk).where(DocumentChunk.id == chunk.id))
        await session.commit()

    assert await stored(session_factory) == []


async def test_embeddings_go_away_with_their_document(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk = await create_chunk(session_factory)
    await add(session_factory, embedding_for(chunk))

    async with session_factory() as session:
        await session.execute(delete(Document).where(Document.id == chunk.document_id))
        await session.commit()

    assert await stored(session_factory) == []


async def test_replacing_chunks_removes_their_embeddings(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk = await create_chunk(session_factory)
    await add(session_factory, embedding_for(chunk))

    async with session_factory() as session:
        await DocumentChunkRepository(session).replace_for_document(
            chunk.document_id, chunk_text("Completely different text now.")
        )
        await session.commit()

    assert await stored(session_factory) == []


async def test_vectors_of_different_sizes_cannot_be_compared(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chunk = await create_chunk(session_factory)
    await add(session_factory, embedding_for(chunk))

    async with session_factory() as session:
        with pytest.raises(DBAPIError, match="different vector dimensions"):
            await session.scalars(
                select(ChunkEmbedding.id).order_by(
                    ChunkEmbedding.embedding.cosine_distance([1.0, 2.0])
                )
            )
