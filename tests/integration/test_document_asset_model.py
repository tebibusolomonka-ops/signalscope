import hashlib
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

SHA256 = hashlib.sha256(b"hello").hexdigest()


async def create_document(session_factory: async_sessionmaker[AsyncSession]) -> Document:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Uploads")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, title="Report")
        session.add(document)
        await session.commit()
    return document


def asset_for(document: Document, **values: Any) -> DocumentAsset:
    fields: dict[str, Any] = {
        "document_id": document.id,
        "storage_key": f"ab/{uuid.uuid4().hex}",
        "filename": "report.pdf",
        "content_type": "application/pdf",
        "size_bytes": 5,
        "sha256": SHA256,
    }
    return DocumentAsset(**(fields | values))


async def add_asset(
    session_factory: async_sessionmaker[AsyncSession], asset: DocumentAsset
) -> DocumentAsset:
    async with session_factory() as session:
        session.add(asset)
        await session.commit()
    return asset


async def test_asset_is_saved(session_factory: async_sessionmaker[AsyncSession]) -> None:
    document = await create_document(session_factory)
    asset = await add_asset(session_factory, asset_for(document))

    async with session_factory() as session:
        saved = await session.get(DocumentAsset, asset.id)

    assert saved is not None
    assert (saved.document_id, saved.content_type, saved.size_bytes, saved.sha256) == (
        document.id,
        "application/pdf",
        5,
        SHA256,
    )
    assert saved.created_at is not None


async def test_a_document_cannot_have_two_assets(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    document = await create_document(session_factory)
    await add_asset(session_factory, asset_for(document))

    async with session_factory() as session:
        session.add(asset_for(document))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_storage_key_is_unique(session_factory: async_sessionmaker[AsyncSession]) -> None:
    first = await create_document(session_factory)
    second = await create_document(session_factory)
    await add_asset(session_factory, asset_for(first, storage_key="ab/same"))

    async with session_factory() as session:
        session.add(asset_for(second, storage_key="ab/same"))
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.parametrize(
    "values",
    [
        {"size_bytes": -1},
        {"sha256": "abc"},
        {"sha256": SHA256.upper()},
        {"sha256": "g" * 64},
        {"document_id": uuid.uuid4()},
    ],
)
async def test_invalid_asset_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, Any]
) -> None:
    document = await create_document(session_factory)

    async with session_factory() as session:
        session.add(asset_for(document, **values))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_document_with_an_asset_needs_file_storage_to_be_deleted(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    document = await create_document(session_factory)
    await add_asset(session_factory, asset_for(document))

    # The test app has no SIGNALSCOPE_BLOB_DIR, so the file could not be removed.
    response = await client.delete(f"/documents/{document.id}")

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "service_unavailable", "message": "File storage is not configured."}
    }
    assert (await client.get(f"/documents/{document.id}")).status_code == 200


async def test_foreign_key_restricts_deletes(database_engine: AsyncEngine) -> None:
    async with database_engine.connect() as connection:
        [foreign_key] = await connection.run_sync(
            lambda sync: inspect(sync).get_foreign_keys("document_assets")
        )

    assert foreign_key["constrained_columns"] == ["document_id"]
    assert foreign_key["referred_table"] == "documents"
    assert foreign_key["options"]["ondelete"] == "RESTRICT"
