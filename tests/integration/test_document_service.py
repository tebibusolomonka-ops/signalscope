import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.domain.documents.repository import DocumentFilters
from signalscope.domain.documents.schemas import DocumentCreate
from signalscope.domain.documents.service import DocumentService
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio


async def create_source(session_factory: async_sessionmaker[AsyncSession], name: str) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.RSS, name=name, url="https://example.com/rss")
        session.add(source)
        await session.commit()
    return source


@pytest.fixture
async def source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    return await create_source(session_factory, "Example feed")


async def test_create_commits_document(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    async with session_factory() as session:
        created = await DocumentService(session).create(
            DocumentCreate(source_id=source.id, external_id="guid-1", title="An article")
        )

    async with session_factory() as session:
        saved = await DocumentService(session).get(created.id)

    assert saved.source_id == source.id
    assert saved.external_id == "guid-1"
    assert saved.title == "An article"


async def test_create_for_unknown_source_raises_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError, match="Source was not found."):
            await DocumentService(session).create(DocumentCreate(source_id=uuid.uuid4()))


async def test_duplicate_external_id_raises_conflict_and_rolls_back(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    async with session_factory() as session:
        service = DocumentService(session)
        await service.create(DocumentCreate(source_id=source.id, external_id="guid-1"))

        with pytest.raises(ConflictError, match="Document already exists for this source."):
            await service.create(DocumentCreate(source_id=source.id, external_id="guid-1"))

        _, total = await service.list_page(DocumentFilters(), limit=10, offset=0)
        assert total == 1


async def test_same_external_id_is_allowed_for_different_sources(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    other_source = await create_source(session_factory, "Other feed")

    async with session_factory() as session:
        service = DocumentService(session)
        await service.create(DocumentCreate(source_id=source.id, external_id="guid-1"))
        await service.create(DocumentCreate(source_id=other_source.id, external_id="guid-1"))

        _, total = await service.list_page(DocumentFilters(), limit=10, offset=0)
        assert total == 2


async def test_documents_without_external_id_do_not_conflict(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    async with session_factory() as session:
        service = DocumentService(session)
        await service.create(DocumentCreate(source_id=source.id, title="One"))
        await service.create(DocumentCreate(source_id=source.id, title="Two"))

        _, total = await service.list_page(DocumentFilters(), limit=10, offset=0)
        assert total == 2


async def test_get_unknown_document_raises_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError, match="Document was not found."):
            await DocumentService(session).get(uuid.uuid4())


async def test_list_page_returns_documents_in_creation_order(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    async with session_factory() as session:
        service = DocumentService(session)
        await service.create(DocumentCreate(source_id=source.id, title="First"))
        await service.create(DocumentCreate(source_id=source.id, title="Second"))

        documents, _ = await service.list_page(DocumentFilters(), limit=10, offset=0)

    assert [document.title for document in documents] == ["First", "Second"]


async def test_delete_removes_document(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    async with session_factory() as session:
        created = await DocumentService(session).create(DocumentCreate(source_id=source.id))

    async with session_factory() as session:
        await DocumentService(session).delete(created.id)

    async with session_factory() as session:
        with pytest.raises(NotFoundError):
            await DocumentService(session).get(created.id)


async def test_delete_unknown_document_raises_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError, match="Document was not found."):
            await DocumentService(session).delete(uuid.uuid4())
