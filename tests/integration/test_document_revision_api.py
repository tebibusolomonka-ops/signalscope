import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.model import Document
from signalscope.domain.documents.revision_repository import DocumentRevisionRepository
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


async def add_revision(
    session_factory: async_sessionmaker[AsyncSession],
    document: Document,
    version: int,
    content: str | None,
) -> None:
    async with session_factory() as session:
        await DocumentRevisionRepository(session).add_snapshot(
            document.id,
            version=version,
            title="Report",
            content=content,
            language="en",
            url=None,
            content_hash=None if content is None else "c" * 64,
            parser_metadata={"page_count": version},
        )
        await session.commit()


async def test_empty_history(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    document = await create_document(session_factory)

    response = await client.get(f"/documents/{document.id}/revisions")

    assert response.status_code == 200
    assert response.json() == {"items": []}


async def test_list_versions(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    document = await create_document(session_factory)
    await add_revision(session_factory, document, 2, "Second text.")
    await add_revision(session_factory, document, 1, None)

    response = await client.get(f"/documents/{document.id}/revisions")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["version"] for item in items] == [1, 2]
    assert [item["content_length"] for item in items] == [None, len("Second text.")]
    assert all("content" not in item for item in items)
    assert items[1]["title"] == "Report"
    assert items[1]["created_at"]


async def test_get_version(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    document = await create_document(session_factory)
    await add_revision(session_factory, document, 1, "First text.")

    response = await client.get(f"/documents/{document.id}/revisions/1")

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == str(document.id)
    assert (body["version"], body["content"], body["language"]) == (1, "First text.", "en")
    assert body["parser_metadata"] == {"page_count": 1}
    assert body["content_hash"] == "c" * 64


@pytest.mark.parametrize("path", ["revisions", "revisions/1"])
async def test_unknown_document(client: httpx.AsyncClient, path: str) -> None:
    response = await client.get(f"/documents/{uuid.uuid4()}/{path}")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Document was not found."}}


async def test_unknown_version(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    document = await create_document(session_factory)
    await add_revision(session_factory, document, 1, "First text.")

    response = await client.get(f"/documents/{document.id}/revisions/2")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Document revision was not found."}
    }
