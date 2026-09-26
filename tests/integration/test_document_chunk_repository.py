import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk, chunk_text
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

SMALL = {"max_chars": 50, "overlap_chars": 10, "min_chars": 25}
FIRST_TEXT = " ".join(f"first{number}" for number in range(40))
SECOND_TEXT = " ".join(f"second{number}" for number in range(15))


async def create_document(
    session_factory: async_sessionmaker[AsyncSession], content: str
) -> Document:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, content=content)
        session.add(document)
        await session.commit()
    return document


async def replace(
    session_factory: async_sessionmaker[AsyncSession], document: Document, text: str
) -> None:
    async with session_factory() as session:
        await DocumentChunkRepository(session).replace_for_document(
            document.id, chunk_text(text, **SMALL)
        )
        await session.commit()


async def stored_texts(
    session_factory: async_sessionmaker[AsyncSession], document: Document
) -> list[tuple[int, str]]:
    async with session_factory() as session:
        chunks = await DocumentChunkRepository(session).list_by_document(document.id)
    return [(chunk.position, chunk.text) for chunk in chunks]


async def test_chunks_are_stored_in_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory, FIRST_TEXT)
    expected = chunk_text(FIRST_TEXT, **SMALL)

    await replace(session_factory, document, FIRST_TEXT)

    async with session_factory() as session:
        chunks = await DocumentChunkRepository(session).list_by_document(document.id)
    assert len(chunks) == len(expected) > 1
    for stored, chunk in zip(chunks, expected, strict=True):
        assert (stored.position, stored.text, stored.start_char, stored.end_char) == (
            chunk.position,
            chunk.text,
            chunk.start_char,
            chunk.end_char,
        )
        assert stored.text_hash == chunk.text_hash


async def test_replace_removes_the_old_chunks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory, FIRST_TEXT)
    await replace(session_factory, document, FIRST_TEXT)

    await replace(session_factory, document, SECOND_TEXT)

    assert await stored_texts(session_factory, document) == [
        (chunk.position, chunk.text) for chunk in chunk_text(SECOND_TEXT, **SMALL)
    ]


async def test_empty_replacement_deletes_all_chunks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory, FIRST_TEXT)
    await replace(session_factory, document, FIRST_TEXT)

    await replace(session_factory, document, "")

    assert await stored_texts(session_factory, document) == []


async def test_other_documents_keep_their_chunks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory, FIRST_TEXT)
    other = await create_document(session_factory, SECOND_TEXT)
    await replace(session_factory, other, SECOND_TEXT)

    await replace(session_factory, document, FIRST_TEXT)
    await replace(session_factory, document, "")

    assert len(await stored_texts(session_factory, other)) == len(chunk_text(SECOND_TEXT, **SMALL))


async def test_rollback_keeps_the_old_chunks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory, FIRST_TEXT)
    await replace(session_factory, document, FIRST_TEXT)
    before = await stored_texts(session_factory, document)

    async with session_factory() as session:
        await DocumentChunkRepository(session).replace_for_document(
            document.id, chunk_text(SECOND_TEXT, **SMALL)
        )
        await session.rollback()

    assert await stored_texts(session_factory, document) == before


async def test_replace_does_not_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory, FIRST_TEXT)

    async with session_factory() as session:
        await DocumentChunkRepository(session).replace_for_document(
            document.id, chunk_text(FIRST_TEXT, **SMALL)
        )

    assert await stored_texts(session_factory, document) == []


async def test_chunk_metadata_is_stored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory, "Page text.")
    chunk = chunk_text("Page text.")[0]
    with_metadata = TextChunk(
        position=chunk.position,
        text=chunk.text,
        start_char=chunk.start_char,
        end_char=chunk.end_char,
        text_hash=chunk.text_hash,
        metadata={"page_number": 3, "section_kind": "page", "section_index": 2},
    )

    async with session_factory() as session:
        await DocumentChunkRepository(session).replace_for_document(document.id, [with_metadata])
        await session.commit()

    async with session_factory() as session:
        [stored] = await DocumentChunkRepository(session).list_by_document(document.id)
    assert stored.chunk_metadata == {"page_number": 3, "section_kind": "page", "section_index": 2}


async def test_chunk_metadata_defaults_to_an_empty_object(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory, FIRST_TEXT)
    await replace(session_factory, document, FIRST_TEXT)

    async with session_factory() as session:
        chunks = await DocumentChunkRepository(session).list_by_document(document.id)
    assert all(chunk.chunk_metadata == {} for chunk in chunks)


async def test_chunk_metadata_must_be_an_object(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory, FIRST_TEXT)

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO document_chunks (id, document_id, position, text, start_char, "
                    "end_char, text_hash, metadata) VALUES (gen_random_uuid(), :document_id, 0, "
                    "'x', 0, 1, :text_hash, '[1]'::jsonb)"
                ),
                {"document_id": document.id, "text_hash": "d" * 64},
            )
