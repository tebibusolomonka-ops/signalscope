import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.model import Document
from signalscope.domain.documents.repository import DocumentRepository
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio


@pytest.fixture
async def source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.RSS, name="Example feed", url="https://example.com/rss")
        session.add(source)
        await session.commit()
    return source


async def add_document(
    session_factory: async_sessionmaker[AsyncSession], source: Source, title: str
) -> Document:
    async with session_factory() as session:
        document = await DocumentRepository(session).add(Document(source_id=source.id, title=title))
        await session.commit()
    return document


async def test_add_and_get(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    published_at = datetime(2026, 3, 1, 12, 30, tzinfo=UTC)
    async with session_factory() as session:
        document = await DocumentRepository(session).add(
            Document(
                source_id=source.id,
                external_id="item-1",
                title="An article",
                content="Some text.",
                language="en",
                published_at=published_at,
            )
        )
        await session.commit()

    async with session_factory() as session:
        saved = await DocumentRepository(session).get(document.id)

    assert saved is not None
    assert saved.source_id == source.id
    assert saved.external_id == "item-1"
    assert saved.title == "An article"
    assert saved.content == "Some text."
    assert saved.language == "en"
    assert saved.published_at == published_at
    assert saved.created_at == document.created_at


async def test_get_returns_none_for_unknown_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        assert await DocumentRepository(session).get(uuid.uuid4()) is None


async def test_add_does_not_commit(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    async with session_factory() as session:
        document = await DocumentRepository(session).add(Document(source_id=source.id))

    async with session_factory() as session:
        assert await DocumentRepository(session).get(document.id) is None


async def test_list_all_returns_documents_in_creation_order(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    await add_document(session_factory, source, "First")
    await add_document(session_factory, source, "Second")
    await add_document(session_factory, source, "Third")

    async with session_factory() as session:
        documents = await DocumentRepository(session).list_all()

    assert [document.title for document in documents] == ["First", "Second", "Third"]


async def test_list_all_breaks_ties_by_id(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    # Rows added in one transaction share created_at, so the ID decides the order.
    async with session_factory() as session:
        repository = DocumentRepository(session)
        for title in ["A", "B", "C", "D"]:
            await repository.add(Document(source_id=source.id, title=title))
        await session.commit()

    async with session_factory() as session:
        documents = await DocumentRepository(session).list_all()

    assert len({document.created_at for document in documents}) == 1
    assert [document.id for document in documents] == sorted(document.id for document in documents)


async def test_delete_removes_document(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    document = await add_document(session_factory, source, "Old news")

    async with session_factory() as session:
        deleted = await DocumentRepository(session).delete(document.id)
        await session.commit()

    async with session_factory() as session:
        assert await DocumentRepository(session).get(document.id) is None
    assert deleted is True


async def test_delete_returns_false_for_unknown_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        assert await DocumentRepository(session).delete(uuid.uuid4()) is False
