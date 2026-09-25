import hashlib
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.extraction import DocumentExtraction
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

PROCESSED_AT = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


async def create_asset(session_factory: async_sessionmaker[AsyncSession]) -> DocumentAsset:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Uploads")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id)
        session.add(document)
        await session.flush()
        asset = DocumentAsset(
            document_id=document.id,
            storage_key=f"ab/{uuid.uuid4().hex}",
            content_type="application/pdf",
            size_bytes=5,
            sha256=hashlib.sha256(b"hello").hexdigest(),
        )
        session.add(asset)
        await session.commit()
    return asset


def extraction_for(asset: DocumentAsset, **values: Any) -> DocumentExtraction:
    fields: dict[str, Any] = {
        "document_id": asset.document_id,
        "asset_id": asset.id,
        "parser_name": "PdfDocumentParser",
        "content_type": "application/pdf",
        "parser_metadata": {"page_count": 3, "truncated": False, "author": "Jane"},
        "text_length": 1200,
        "processed_at": PROCESSED_AT,
    }
    return DocumentExtraction(**(fields | values))


async def add(
    session_factory: async_sessionmaker[AsyncSession], extraction: DocumentExtraction
) -> DocumentExtraction:
    async with session_factory() as session:
        session.add(extraction)
        await session.commit()
    return extraction


async def reload(
    session_factory: async_sessionmaker[AsyncSession], extraction_id: uuid.UUID
) -> DocumentExtraction:
    async with session_factory() as session:
        saved = await session.get(DocumentExtraction, extraction_id)
    assert saved is not None
    return saved


async def test_extraction_is_saved(session_factory: async_sessionmaker[AsyncSession]) -> None:
    asset = await create_asset(session_factory)
    extraction = await add(session_factory, extraction_for(asset))

    saved = await reload(session_factory, extraction.id)

    assert (saved.document_id, saved.asset_id) == (asset.document_id, asset.id)
    assert (saved.parser_name, saved.content_type) == ("PdfDocumentParser", "application/pdf")
    assert saved.parser_metadata == {"page_count": 3, "truncated": False, "author": "Jane"}
    assert saved.text_length == 1200
    assert saved.processed_at == PROCESSED_AT


async def test_metadata_keeps_json_types(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    asset = await create_asset(session_factory)
    metadata = {"text": "Zoë – 東京", "count": 7, "ratio": 0.5, "flag": True}
    extraction = await add(session_factory, extraction_for(asset, parser_metadata=metadata))

    assert (await reload(session_factory, extraction.id)).parser_metadata == metadata


async def test_metadata_defaults_to_an_empty_object(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    asset = await create_asset(session_factory)
    extraction = DocumentExtraction(
        document_id=asset.document_id,
        asset_id=asset.id,
        parser_name="PlainTextParser",
        content_type="text/plain",
        text_length=0,
        processed_at=PROCESSED_AT,
    )
    await add(session_factory, extraction)

    assert (await reload(session_factory, extraction.id)).parser_metadata == {}


async def test_processed_at_keeps_the_instant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    asset = await create_asset(session_factory)
    local_time = datetime(2026, 5, 1, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    extraction = await add(session_factory, extraction_for(asset, processed_at=local_time))

    assert (await reload(session_factory, extraction.id)).processed_at == PROCESSED_AT


async def test_one_extraction_per_document(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    asset = await create_asset(session_factory)
    await add(session_factory, extraction_for(asset))

    async with session_factory() as session:
        session.add(extraction_for(asset))
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.parametrize(
    "values",
    [{"text_length": -1}, {"asset_id": uuid.uuid4()}, {"document_id": uuid.uuid4()}],
)
async def test_invalid_extraction_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, Any]
) -> None:
    asset = await create_asset(session_factory)

    async with session_factory() as session:
        session.add(extraction_for(asset, **values))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_metadata_must_be_an_object(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    asset = await create_asset(session_factory)

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO document_extractions (id, document_id, asset_id, parser_name, "
                    "content_type, metadata, text_length, processed_at) VALUES (:id, "
                    ":document_id, :asset_id, 'p', 'text/plain', '[1, 2]'::jsonb, 0, now())"
                ),
                {"id": uuid.uuid4(), "document_id": asset.document_id, "asset_id": asset.id},
            )


@pytest.mark.parametrize("table", ["asset", "document"])
async def test_extraction_keeps_its_asset_and_document(
    session_factory: async_sessionmaker[AsyncSession], table: str
) -> None:
    asset = await create_asset(session_factory)
    await add(session_factory, extraction_for(asset))
    statement = (
        delete(DocumentAsset).where(DocumentAsset.id == asset.id)
        if table == "asset"
        else delete(Document).where(Document.id == asset.document_id)
    )

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(statement)
