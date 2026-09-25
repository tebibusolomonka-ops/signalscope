import hashlib
import uuid
from typing import Any

import pytest
from sqlalchemy import delete, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

CONTENT = "First chunk text. Second chunk text."


async def create_document(session_factory: async_sessionmaker[AsyncSession]) -> Document:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, content=CONTENT)
        session.add(document)
        await session.commit()
    return document


def chunk_for(document: Document, **values: Any) -> DocumentChunk:
    text = values.pop("text", "First chunk text.")
    fields: dict[str, Any] = {
        "document_id": document.id,
        "position": 0,
        "text": text,
        "start_char": 0,
        "end_char": len(text),
        "text_hash": hashlib.sha256(text.encode()).hexdigest(),
    }
    return DocumentChunk(**(fields | values))


async def add(session_factory: async_sessionmaker[AsyncSession], *chunks: DocumentChunk) -> None:
    async with session_factory() as session:
        session.add_all(chunks)
        await session.commit()


async def test_chunks_are_saved(session_factory: async_sessionmaker[AsyncSession]) -> None:
    document = await create_document(session_factory)
    second_text = "Second chunk text."
    start = CONTENT.index(second_text)
    await add(
        session_factory,
        chunk_for(document),
        chunk_for(
            document,
            position=1,
            text=second_text,
            start_char=start,
            end_char=start + len(second_text),
        ),
    )

    async with session_factory() as session:
        chunks = list(
            await session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document.id)
                .order_by(DocumentChunk.position)
            )
        )

    assert [chunk.position for chunk in chunks] == [0, 1]
    for chunk in chunks:
        assert CONTENT[chunk.start_char : chunk.end_char] == chunk.text
        assert chunk.text_hash == hashlib.sha256(chunk.text.encode()).hexdigest()


async def test_position_is_unique_per_document(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory)
    other = await create_document(session_factory)
    await add(session_factory, chunk_for(document), chunk_for(other))

    async with session_factory() as session:
        session.add(chunk_for(document))
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.parametrize(
    "values",
    [
        {"position": -1},
        {"start_char": -1},
        {"start_char": 10, "end_char": 5},
        {"text": "", "end_char": 0},
        {"text_hash": "abc"},
        {"text_hash": "A" * 64},
        {"document_id": uuid.uuid4()},
    ],
)
async def test_invalid_chunk_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, Any]
) -> None:
    document = await create_document(session_factory)

    async with session_factory() as session:
        session.add(chunk_for(document, **values))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_chunks_are_deleted_with_their_document(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory)
    await add(session_factory, chunk_for(document))

    async with session_factory() as session:
        await session.execute(delete(Document).where(Document.id == document.id))
        await session.commit()

    async with session_factory() as session:
        assert list(await session.scalars(select(DocumentChunk))) == []


async def test_foreign_key_cascades(database_engine: AsyncEngine) -> None:
    async with database_engine.connect() as connection:
        [foreign_key] = await connection.run_sync(
            lambda sync: inspect(sync).get_foreign_keys("document_chunks")
        )

    assert foreign_key["referred_table"] == "documents"
    assert foreign_key["options"]["ondelete"] == "CASCADE"


async def test_document_id_leads_the_unique_index(database_engine: AsyncEngine) -> None:
    async with database_engine.connect() as connection:
        constraints = await connection.run_sync(
            lambda sync: inspect(sync).get_unique_constraints("document_chunks")
        )

    assert [constraint["column_names"] for constraint in constraints] == [
        ["document_id", "position"]
    ]
