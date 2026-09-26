import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.asset_service import DocumentAssetService
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.fingerprint import content_fingerprint
from signalscope.domain.documents.model import Document
from signalscope.domain.documents.revision import DocumentRevision
from signalscope.domain.documents.revision_repository import DocumentRevisionRepository
from signalscope.domain.processing.processor import DocumentProcessor, ProcessingResult
from signalscope.domain.sources.model import Source, SourceType
from signalscope.parsing.registry import create_default_parser_registry
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def blobs(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(tmp_path / "blobs")


@pytest.fixture
async def asset(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> DocumentAsset:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, title="Report")
        session.add(document)
        await session.commit()
        return await DocumentAssetService(session, blobs).attach(
            document.id, filename="report.txt", content_type="text/plain", data=b"First text."
        )


async def process(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    asset: DocumentAsset,
    data: bytes | None = None,
    now: datetime = NOW,
) -> ProcessingResult:
    if data is not None:
        await blobs.put(asset.storage_key, data)
    processor = DocumentProcessor(
        session_factory, blobs, create_default_parser_registry(), clock=lambda: now
    )
    return await processor.process(asset.id)


async def revisions(
    session_factory: async_sessionmaker[AsyncSession], document_id: uuid.UUID
) -> list[DocumentRevision]:
    async with session_factory() as session:
        return await DocumentRevisionRepository(session).list_by_document(document_id)


async def document(
    session_factory: async_sessionmaker[AsyncSession], document_id: uuid.UUID
) -> Document:
    async with session_factory() as session:
        saved = await session.get(Document, document_id)
    assert saved is not None
    return saved


async def test_first_processing_keeps_no_revision(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, asset: DocumentAsset
) -> None:
    result = await process(session_factory, blobs, asset)

    assert result.revision is None
    assert await revisions(session_factory, asset.document_id) == []


async def test_changed_content_keeps_the_earlier_state(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, asset: DocumentAsset
) -> None:
    await process(session_factory, blobs, asset)

    result = await process(session_factory, blobs, asset, b"Second text.")

    [revision] = await revisions(session_factory, asset.document_id)
    assert result.revision is not None
    assert result.revision.id == revision.id
    assert revision.version == 1
    assert (revision.title, revision.content) == ("Report", "First text.")
    assert revision.content_hash == content_fingerprint(
        title="Report", content="First text.", url=None
    )
    assert revision.parser_metadata == {"encoding": "utf-8"}
    current = await document(session_factory, asset.document_id)
    assert current.content == "Second text."
    async with session_factory() as session:
        chunks = await DocumentChunkRepository(session).list_by_document(asset.document_id)
    assert [chunk.text for chunk in chunks] == ["Second text."]


async def test_each_change_adds_a_version(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, asset: DocumentAsset
) -> None:
    await process(session_factory, blobs, asset)
    await process(session_factory, blobs, asset, b"Second text.")

    await process(session_factory, blobs, asset, b"Third text.")

    history = await revisions(session_factory, asset.document_id)
    assert [(revision.version, revision.content) for revision in history] == [
        (1, "First text."),
        (2, "Second text."),
    ]
    assert (await document(session_factory, asset.document_id)).content == "Third text."


async def test_unchanged_content_adds_no_revision(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, asset: DocumentAsset
) -> None:
    await process(session_factory, blobs, asset)
    later = NOW + timedelta(hours=1)

    result = await process(session_factory, blobs, asset, now=later)

    assert result.revision is None
    assert await revisions(session_factory, asset.document_id) == []
    # The processing itself is still recorded.
    assert result.extraction.processed_at == later


async def test_failed_save_keeps_no_revision(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    asset: DocumentAsset,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await process(session_factory, blobs, asset)

    async def broken_replace(
        self: DocumentChunkRepository, document_id: uuid.UUID, chunks: list[TextChunk]
    ) -> None:
        raise RuntimeError("database is down")

    monkeypatch.setattr(DocumentChunkRepository, "replace_for_document", broken_replace)

    with pytest.raises(RuntimeError, match="database is down"):
        await process(session_factory, blobs, asset, b"Second text.")

    assert await revisions(session_factory, asset.document_id) == []
    assert (await document(session_factory, asset.document_id)).content == "First text."
