import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import InvalidInputError
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import chunk_text
from signalscope.domain.documents.model import Document
from signalscope.domain.search.service import SearchService
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio


async def add_document(session_factory: async_sessionmaker[AsyncSession], content: str) -> Document:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, title="Report", content=content)
        session.add(document)
        await session.flush()
        await DocumentChunkRepository(session).replace_for_document(
            document.id, chunk_text(content)
        )
        await session.commit()
    return document


async def test_search(session_factory: async_sessionmaker[AsyncSession]) -> None:
    document = await add_document(session_factory, "Climate policy for coastal cities.")
    await add_document(session_factory, "Budget report.")

    async with session_factory() as session:
        results = await SearchService(session).search("  Climate  ")

    assert [result.document_id for result in results] == [document.id]
    assert results[0].title == "Report"


async def test_source_filter(session_factory: async_sessionmaker[AsyncSession]) -> None:
    first = await add_document(session_factory, "Climate report one.")
    second = await add_document(session_factory, "Climate report two.")

    async with session_factory() as session:
        results = await SearchService(session).search("climate", source_id=second.source_id)

    assert [result.document_id for result in results] == [second.id]
    assert first.id not in [result.document_id for result in results]


async def test_limit(session_factory: async_sessionmaker[AsyncSession]) -> None:
    for number in range(3):
        await add_document(session_factory, f"Climate report {number}.")

    async with session_factory() as session:
        results = await SearchService(session).search("climate", limit=2)

    assert len(results) == 2


async def test_blank_query(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        with pytest.raises(InvalidInputError, match="must not be empty"):
            await SearchService(session).search("   ")
