from typing import Any

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.model import Document
from signalscope.domain.documents.revision import DocumentRevision
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio


async def create_document(session_factory: async_sessionmaker[AsyncSession]) -> Document:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, title="Report", content="Current text.")
        session.add(document)
        await session.commit()
    return document


def revision_for(document: Document, **values: Any) -> DocumentRevision:
    fields: dict[str, Any] = {
        "document_id": document.id,
        "version": 1,
        "title": "Report",
        "content": "Older text.",
        "language": "en",
        "url": None,
        "content_hash": "a" * 64,
        "parser_metadata": {"page_count": 2, "truncated": False, "author": "Zoë"},
    }
    return DocumentRevision(**(fields | values))


async def add(
    session_factory: async_sessionmaker[AsyncSession], *revisions: DocumentRevision
) -> None:
    async with session_factory() as session:
        session.add_all(revisions)
        await session.commit()


async def stored(session_factory: async_sessionmaker[AsyncSession]) -> list[DocumentRevision]:
    async with session_factory() as session:
        return list(
            await session.scalars(select(DocumentRevision).order_by(DocumentRevision.version))
        )


async def test_revision_is_saved(session_factory: async_sessionmaker[AsyncSession]) -> None:
    document = await create_document(session_factory)
    await add(session_factory, revision_for(document))

    [revision] = await stored(session_factory)

    assert (revision.document_id, revision.version) == (document.id, 1)
    assert (revision.title, revision.content, revision.language) == (
        "Report",
        "Older text.",
        "en",
    )
    assert revision.parser_metadata == {"page_count": 2, "truncated": False, "author": "Zoë"}
    assert revision.created_at is not None


async def test_empty_content_and_metadata(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory)
    await add(
        session_factory,
        DocumentRevision(document_id=document.id, version=1),
    )

    [revision] = await stored(session_factory)

    assert (revision.content, revision.title, revision.content_hash) == (None, None, None)
    assert revision.parser_metadata == {}


async def test_versions_of_one_document(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory)
    other = await create_document(session_factory)
    await add(
        session_factory,
        revision_for(document),
        revision_for(document, version=2),
        revision_for(other),
    )

    assert [revision.version for revision in await stored(session_factory)] == [1, 1, 2]


async def test_version_is_unique_per_document(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory)
    await add(session_factory, revision_for(document))

    async with session_factory() as session:
        session.add(revision_for(document))
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.parametrize("version", [0, -1])
async def test_version_must_be_positive(
    session_factory: async_sessionmaker[AsyncSession], version: int
) -> None:
    document = await create_document(session_factory)

    async with session_factory() as session:
        session.add(revision_for(document, version=version))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_metadata_must_be_an_object(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory)

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO document_revisions (id, document_id, version, metadata) "
                    "VALUES (gen_random_uuid(), :document_id, 1, '[]'::jsonb)"
                ),
                {"document_id": document.id},
            )


async def test_revisions_are_deleted_with_their_document(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory)
    await add(session_factory, revision_for(document), revision_for(document, version=2))

    async with session_factory() as session:
        await session.execute(delete(Document).where(Document.id == document.id))
        await session.commit()

    assert await stored(session_factory) == []
