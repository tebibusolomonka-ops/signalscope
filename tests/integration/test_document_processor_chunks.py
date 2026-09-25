import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sample_files import make_docx, make_pdf
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.asset_service import DocumentAssetService
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk, chunk_text
from signalscope.domain.documents.extraction import DocumentExtraction
from signalscope.domain.documents.model import Document
from signalscope.domain.processing.processor import DocumentProcessor
from signalscope.domain.sources.model import Source, SourceType
from signalscope.parsing.docx_document import DOCX_CONTENT_TYPE
from signalscope.parsing.registry import create_default_parser_registry
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio

LONG_TEXT = "\n\n".join(
    f"Paragraph {number} about climate policy. " + "Details follow here. " * 20
    for number in range(8)
)


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
    content_type: str = "text/plain",
) -> DocumentAsset:
    async with session_factory() as session:
        document = Document(source_id=source.id, title="Report")
        session.add(document)
        await session.commit()
        return await DocumentAssetService(session, blobs).attach(
            document.id, filename="report", content_type=content_type, data=data
        )


async def process(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, asset_id: uuid.UUID
) -> None:
    processor = DocumentProcessor(session_factory, blobs, create_default_parser_registry())
    await processor.process(asset_id)


async def stored(
    session_factory: async_sessionmaker[AsyncSession], document_id: uuid.UUID
) -> tuple[Document, DocumentExtraction | None, list[DocumentChunk]]:
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        extraction = await session.scalar(
            select(DocumentExtraction).where(DocumentExtraction.document_id == document_id)
        )
        chunks = await DocumentChunkRepository(session).list_by_document(document_id)
    assert document is not None
    return document, extraction, chunks


def as_tuples(chunks: list[DocumentChunk] | list[TextChunk]) -> list[tuple[int, int, int, str]]:
    return [(chunk.position, chunk.start_char, chunk.end_char, chunk.text) for chunk in chunks]


async def test_text_file_gets_chunks(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    asset = await store(session_factory, blobs, source, LONG_TEXT.encode())

    await process(session_factory, blobs, asset.id)

    document, extraction, chunks = await stored(session_factory, asset.document_id)
    assert document.content == LONG_TEXT
    assert extraction is not None
    assert extraction.text_length == len(LONG_TEXT)
    assert len(chunks) > 1
    assert as_tuples(chunks) == as_tuples(chunk_text(LONG_TEXT))
    for chunk in chunks:
        assert document.content[chunk.start_char : chunk.end_char] == chunk.text


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        (make_pdf(["Climate page one", "Policy page two"]), "application/pdf"),
        (make_docx(["Climate memo", "Policy notes"]), DOCX_CONTENT_TYPE),
    ],
    ids=["pdf", "docx"],
)
async def test_pdf_and_docx_get_chunks(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    source: Source,
    data: bytes,
    content_type: str,
) -> None:
    asset = await store(session_factory, blobs, source, data, content_type)

    await process(session_factory, blobs, asset.id)

    document, _, chunks = await stored(session_factory, asset.document_id)
    assert document.content
    assert as_tuples(chunks) == as_tuples(chunk_text(document.content))
    assert [chunk.position for chunk in chunks] == [0]


async def test_empty_text_has_no_chunks(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    asset = await store(session_factory, blobs, source, make_pdf([None]), "application/pdf")

    await process(session_factory, blobs, asset.id)

    document, extraction, chunks = await stored(session_factory, asset.document_id)
    assert document.content == ""
    assert extraction is not None
    assert chunks == []


async def test_processing_again_replaces_the_chunks(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    asset = await store(session_factory, blobs, source, LONG_TEXT.encode())
    await process(session_factory, blobs, asset.id)
    shorter = "A much shorter text about policy."
    await blobs.put(asset.storage_key, shorter.encode())

    await process(session_factory, blobs, asset.id)

    document, extraction, chunks = await stored(session_factory, asset.document_id)
    assert document.content == shorter
    assert extraction is not None
    assert extraction.text_length == len(shorter)
    assert as_tuples(chunks) == [(0, 0, len(shorter), shorter)]


async def test_processing_twice_does_not_duplicate_chunks(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    asset = await store(session_factory, blobs, source, LONG_TEXT.encode())

    await process(session_factory, blobs, asset.id)
    await process(session_factory, blobs, asset.id)

    _, _, chunks = await stored(session_factory, asset.document_id)
    assert as_tuples(chunks) == as_tuples(chunk_text(LONG_TEXT))


async def test_failed_chunk_save_saves_nothing(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    source: Source,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = await store(session_factory, blobs, source, LONG_TEXT.encode())

    async def broken_replace(
        self: DocumentChunkRepository, document_id: uuid.UUID, chunks: list[TextChunk]
    ) -> None:
        raise RuntimeError("database is down")

    monkeypatch.setattr(DocumentChunkRepository, "replace_for_document", broken_replace)

    with pytest.raises(RuntimeError, match="database is down"):
        await process(session_factory, blobs, asset.id)

    document, extraction, chunks = await stored(session_factory, asset.document_id)
    assert (document.content, document.content_hash) == (None, None)
    assert extraction is None
    assert chunks == []


async def test_failed_reprocessing_keeps_the_earlier_result(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    source: Source,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = await store(session_factory, blobs, source, LONG_TEXT.encode())
    await process(session_factory, blobs, asset.id)
    await blobs.put(asset.storage_key, b"New text that is never saved.")

    async def broken_replace(
        self: DocumentChunkRepository, document_id: uuid.UUID, chunks: list[TextChunk]
    ) -> None:
        raise RuntimeError("database is down")

    monkeypatch.setattr(DocumentChunkRepository, "replace_for_document", broken_replace)

    with pytest.raises(RuntimeError):
        await process(session_factory, blobs, asset.id)

    document, extraction, chunks = await stored(session_factory, asset.document_id)
    assert document.content == LONG_TEXT
    assert extraction is not None
    assert extraction.text_length == len(LONG_TEXT)
    assert as_tuples(chunks) == as_tuples(chunk_text(LONG_TEXT))
