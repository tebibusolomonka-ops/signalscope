import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sample_files import make_docx, make_pdf
from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.asset_service import DocumentAssetService
from signalscope.domain.documents.extraction import DocumentExtraction
from signalscope.domain.documents.fingerprint import content_fingerprint
from signalscope.domain.documents.model import Document
from signalscope.domain.processing.processor import DocumentProcessor
from signalscope.domain.sources.model import Source, SourceType
from signalscope.parsing.docx_document import DOCX_CONTENT_TYPE
from signalscope.parsing.registry import create_default_parser_registry
from signalscope.parsing.types import DocumentParsingError, UnsupportedDocumentTypeError
from signalscope.storage.blob import BlobNotFoundError
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def blobs(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(tmp_path / "blobs")


@pytest.fixture
async def source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.commit()
    return source


async def store(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    source: Source,
    data: bytes,
    content_type: str,
    filename: str = "upload",
    title: str | None = None,
    language: str | None = None,
) -> DocumentAsset:
    async with session_factory() as session:
        document = Document(source_id=source.id, title=title, language=language)
        session.add(document)
        await session.commit()
        return await DocumentAssetService(session, blobs).attach(
            document.id, filename=filename, content_type=content_type, data=data
        )


def processor(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    now: datetime = NOW,
) -> DocumentProcessor:
    return DocumentProcessor(
        session_factory, blobs, create_default_parser_registry(), clock=lambda: now
    )


async def saved(
    session_factory: async_sessionmaker[AsyncSession], document_id: uuid.UUID
) -> tuple[Document, DocumentExtraction | None]:
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        extraction = await session.scalar(
            select(DocumentExtraction).where(DocumentExtraction.document_id == document_id)
        )
    assert document is not None
    return document, extraction


async def test_plain_text(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    text = "First paragraph.\n\nSecond paragraph.\n"
    asset = await store(
        session_factory,
        blobs,
        source,
        text.encode(),
        "text/plain; charset=utf-8",
        filename="Field notes.txt",
    )

    result = await processor(session_factory, blobs).process(asset.id)

    document, extraction = await saved(session_factory, asset.document_id)
    assert result.document.id == document.id
    assert document.content == text
    assert document.title == "Field notes"
    assert document.content_hash == content_fingerprint(title="Field notes", content=text, url=None)
    assert extraction is not None
    assert extraction.asset_id == asset.id
    assert extraction.parser_name == "PlainTextParser"
    assert extraction.content_type == "text/plain; charset=utf-8"
    assert extraction.parser_metadata == {"encoding": "utf-8"}
    assert extraction.text_length == len(text)
    assert extraction.processed_at == NOW


async def test_json(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    data = json.dumps({"title": "Budget", "items": [1, 2]}).encode()
    asset = await store(session_factory, blobs, source, data, "application/json")

    await processor(session_factory, blobs).process(asset.id)

    document, extraction = await saved(session_factory, asset.document_id)
    assert document.content == "title: Budget\nitems[0]: 1\nitems[1]: 2"
    assert document.title == "Budget"
    assert extraction is not None
    assert extraction.parser_name == "JsonParser"
    assert extraction.parser_metadata == {"truncated": False}


async def test_html_fills_in_title_and_language(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    html = b'<html lang="fr"><head><title>Bonjour</title></head><body><p>Salut</p></body></html>'
    asset = await store(session_factory, blobs, source, html, "text/html")

    await processor(session_factory, blobs).process(asset.id)

    document, extraction = await saved(session_factory, asset.document_id)
    assert (document.content, document.title, document.language) == ("Salut", "Bonjour", "fr")
    assert extraction is not None
    assert extraction.parser_name == "HtmlDocumentParser"


async def test_existing_title_and_language_are_kept(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    html = b'<html lang="fr"><head><title>Bonjour</title></head><body><p>Salut</p></body></html>'
    asset = await store(
        session_factory, blobs, source, html, "text/html", title="Chosen title", language="en"
    )

    await processor(session_factory, blobs).process(asset.id)

    document, _ = await saved(session_factory, asset.document_id)
    assert (document.content, document.title, document.language) == (
        "Salut",
        "Chosen title",
        "en",
    )
    assert document.content_hash == content_fingerprint(
        title="Chosen title", content="Salut", url=None
    )


async def test_blank_title_is_filled_in(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    html = b"<html><head><title>Real title</title></head><body><p>Text</p></body></html>"
    asset = await store(session_factory, blobs, source, html, "text/html", title="   ")

    await processor(session_factory, blobs).process(asset.id)

    assert (await saved(session_factory, asset.document_id))[0].title == "Real title"


async def test_pdf(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    data = make_pdf(["First page", "Second page"], title="Annual Report", author="Jane Doe")
    asset = await store(session_factory, blobs, source, data, "application/pdf")

    await processor(session_factory, blobs).process(asset.id)

    document, extraction = await saved(session_factory, asset.document_id)
    assert document.content == "First page\n\nSecond page"
    assert document.title == "Annual Report"
    assert extraction is not None
    assert extraction.parser_name == "PdfDocumentParser"
    assert extraction.parser_metadata == {
        "page_count": 2,
        "truncated": False,
        "author": "Jane Doe",
    }


async def test_docx(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    data = make_docx(["Hello", "World"], title="Memo", author="Ann")
    asset = await store(session_factory, blobs, source, data, DOCX_CONTENT_TYPE)

    await processor(session_factory, blobs).process(asset.id)

    document, extraction = await saved(session_factory, asset.document_id)
    assert (document.content, document.title) == ("Hello\n\nWorld", "Memo")
    assert extraction is not None
    assert extraction.parser_name == "DocxDocumentParser"
    assert extraction.parser_metadata == {"author": "Ann"}


async def test_file_without_text_is_saved_as_empty(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    asset = await store(session_factory, blobs, source, make_pdf([None]), "application/pdf")

    await processor(session_factory, blobs).process(asset.id)

    document, extraction = await saved(session_factory, asset.document_id)
    assert document.content == ""
    assert extraction is not None
    assert extraction.text_length == 0
    assert extraction.parser_metadata["page_count"] == 1


async def test_unsupported_content_type(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    asset = await store(session_factory, blobs, source, b"\x89PNG", "image/png")

    with pytest.raises(UnsupportedDocumentTypeError, match="No parser is available for image/png"):
        await processor(session_factory, blobs).process(asset.id)

    document, extraction = await saved(session_factory, asset.document_id)
    assert (document.content, extraction) == (None, None)


async def test_missing_blob(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    asset = await store(session_factory, blobs, source, b"hello", "text/plain")
    await blobs.delete(asset.storage_key)

    with pytest.raises(BlobNotFoundError, match="Stored file was not found."):
        await processor(session_factory, blobs).process(asset.id)

    document, extraction = await saved(session_factory, asset.document_id)
    assert (document.content, extraction) == (None, None)


async def test_parser_failure(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    asset = await store(session_factory, blobs, source, b"{not json", "application/json")

    with pytest.raises(DocumentParsingError, match="Document is not valid JSON."):
        await processor(session_factory, blobs).process(asset.id)

    document, extraction = await saved(session_factory, asset.document_id)
    assert (document.content, extraction) == (None, None)


async def test_processing_again_updates_the_same_extraction(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    asset = await store(session_factory, blobs, source, b"Some text", "text/plain")

    await processor(session_factory, blobs).process(asset.id)
    later = NOW + timedelta(hours=1)
    await processor(session_factory, blobs, now=later).process(asset.id)

    _, extraction = await saved(session_factory, asset.document_id)
    assert extraction is not None
    assert extraction.processed_at == later
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(DocumentExtraction))
    assert count == 1


async def test_same_content_twice_in_one_source_is_a_conflict(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    first = await store(session_factory, blobs, source, b"Same text", "text/plain", title="T")
    second = await store(session_factory, blobs, source, b"Same text", "text/plain", title="T")
    await processor(session_factory, blobs).process(first.id)

    with pytest.raises(ConflictError, match="Another document in this source has the same"):
        await processor(session_factory, blobs).process(second.id)

    assert (await saved(session_factory, second.document_id))[0].content is None


async def test_unknown_asset(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    with pytest.raises(NotFoundError, match="Document file was not found."):
        await processor(session_factory, blobs).process(uuid.uuid4())
