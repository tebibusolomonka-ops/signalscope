from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.model import Document
from signalscope.domain.documents.revision import DocumentRevision
from signalscope.domain.documents.revision_repository import DocumentRevisionRepository
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio


async def create_document(session_factory: async_sessionmaker[AsyncSession]) -> Document:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, title="Report")
        session.add(document)
        await session.commit()
    return document


def snapshot(version: int, content: str = "Text.") -> dict[str, Any]:
    return {
        "version": version,
        "title": "Report",
        "content": content,
        "language": "en",
        "url": "https://example.com/report",
        "content_hash": "b" * 64,
        "parser_metadata": {"encoding": "utf-8"},
    }


async def add(
    session_factory: async_sessionmaker[AsyncSession], document: Document, version: int
) -> DocumentRevision:
    async with session_factory() as session:
        revision = await DocumentRevisionRepository(session).add_snapshot(
            document.id, **snapshot(version, f"Text of version {version}.")
        )
        await session.commit()
    return revision


async def test_first_revision(session_factory: async_sessionmaker[AsyncSession]) -> None:
    document = await create_document(session_factory)

    revision = await add(session_factory, document, 1)

    async with session_factory() as session:
        [saved] = await DocumentRevisionRepository(session).list_by_document(document.id)
    assert saved.id == revision.id
    assert (saved.version, saved.content, saved.url) == (
        1,
        "Text of version 1.",
        "https://example.com/report",
    )
    assert saved.parser_metadata == {"encoding": "utf-8"}
    assert saved.created_at is not None


async def test_latest_version(session_factory: async_sessionmaker[AsyncSession]) -> None:
    document = await create_document(session_factory)
    other = await create_document(session_factory)
    async with session_factory() as session:
        assert await DocumentRevisionRepository(session).latest_version(document.id) == 0

    for version in [1, 2, 3]:
        await add(session_factory, document, version)
    await add(session_factory, other, 1)

    async with session_factory() as session:
        repository = DocumentRevisionRepository(session)
        assert await repository.latest_version(document.id) == 3
        assert await repository.latest_version(other.id) == 1


async def test_revisions_are_listed_oldest_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory)
    for version in [2, 3, 1]:
        await add(session_factory, document, version)

    async with session_factory() as session:
        revisions = await DocumentRevisionRepository(session).list_by_document(document.id)

    assert [revision.version for revision in revisions] == [1, 2, 3]


async def test_document_without_revisions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory)

    async with session_factory() as session:
        assert await DocumentRevisionRepository(session).list_by_document(document.id) == []


async def test_taken_version_fails(session_factory: async_sessionmaker[AsyncSession]) -> None:
    document = await create_document(session_factory)
    await add(session_factory, document, 1)

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await DocumentRevisionRepository(session).add_snapshot(document.id, **snapshot(1))


async def test_add_does_not_commit(session_factory: async_sessionmaker[AsyncSession]) -> None:
    document = await create_document(session_factory)

    async with session_factory() as session:
        await DocumentRevisionRepository(session).add_snapshot(document.id, **snapshot(1))

    async with session_factory() as session:
        assert await DocumentRevisionRepository(session).list_by_document(document.id) == []
