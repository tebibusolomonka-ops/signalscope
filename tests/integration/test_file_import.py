import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import ConflictError, InvalidInputError, NotFoundError
from signalscope.domain.documents import files
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.model import Document
from signalscope.domain.processing.file_import import FileImportService, ImportedFile
from signalscope.domain.processing.job_repository import DocumentProcessingJobRepository
from signalscope.domain.processing.model import DocumentProcessingJob, ProcessingJobStatus
from signalscope.domain.sources.model import Source, SourceType
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
TEXT = b"Climate policy notes.\n\nSecond paragraph."


@pytest.fixture
def blob_root(tmp_path: Path) -> Path:
    return tmp_path / "blobs"


@pytest.fixture
def blobs(blob_root: Path) -> LocalBlobStore:
    return LocalBlobStore(blob_root)


async def create_source(
    session_factory: async_sessionmaker[AsyncSession], source_type: SourceType = SourceType.UPLOAD
) -> Source:
    async with session_factory() as session:
        source = Source(type=source_type, name="Files", url="https://example.com/rss")
        session.add(source)
        await session.commit()
    return source


async def import_file(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    source_id: uuid.UUID,
    data: bytes = TEXT,
) -> ImportedFile:
    async with session_factory() as session:
        return await FileImportService(session, blobs, clock=lambda: NOW).import_file(
            source_id, filename="notes/Climate notes.txt", content_type="text/plain", data=data
        )


def stored_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()] if root.exists() else []


async def row_counts(session_factory: async_sessionmaker[AsyncSession]) -> tuple[int, int, int]:
    async with session_factory() as session:
        counts = [
            await session.scalar(select(func.count()).select_from(model))
            for model in [Document, DocumentAsset, DocumentProcessingJob]
        ]
    return counts[0] or 0, counts[1] or 0, counts[2] or 0


async def test_import_creates_document_asset_and_job(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, blob_root: Path
) -> None:
    source = await create_source(session_factory)

    imported = await import_file(session_factory, blobs, source.id)

    async with session_factory() as session:
        document = await session.get(Document, imported.document.id)
        asset = await session.get(DocumentAsset, imported.asset.id)
        job = await session.get(DocumentProcessingJob, imported.job.id)
    assert document is not None
    assert asset is not None
    assert job is not None
    assert document.source_id == source.id
    assert document.title == "Climate notes"
    assert (document.content, document.language, document.content_hash) == (None, None, None)
    assert asset.document_id == document.id
    assert asset.filename == "Climate notes.txt"
    assert asset.content_type == "text/plain"
    assert asset.size_bytes == len(TEXT)
    assert asset.sha256 == hashlib.sha256(TEXT).hexdigest()
    assert (job.document_id, job.asset_id) == (document.id, asset.id)
    assert job.status is ProcessingJobStatus.PENDING
    assert job.available_at == NOW
    assert job.attempt_count == 0


async def test_import_stores_the_bytes(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, blob_root: Path
) -> None:
    source = await create_source(session_factory)

    imported = await import_file(session_factory, blobs, source.id)

    assert await blobs.get(imported.asset.storage_key) == TEXT
    assert [path.read_bytes() for path in stored_files(blob_root)] == [TEXT]


async def test_imported_job_can_be_claimed(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    source = await create_source(session_factory)
    imported = await import_file(session_factory, blobs, source.id)

    async with session_factory() as session:
        claimed = await DocumentProcessingJobRepository(session).claim_next(NOW)

    assert claimed is not None
    assert claimed.id == imported.job.id


async def test_unknown_source(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, blob_root: Path
) -> None:
    with pytest.raises(NotFoundError, match="Source was not found."):
        await import_file(session_factory, blobs, uuid.uuid4())

    assert stored_files(blob_root) == []


@pytest.mark.parametrize("source_type", [SourceType.RSS, SourceType.WEB, SourceType.API])
async def test_only_upload_sources_take_files(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    blob_root: Path,
    source_type: SourceType,
) -> None:
    source = await create_source(session_factory, source_type)

    with pytest.raises(ConflictError, match="only be imported into upload sources"):
        await import_file(session_factory, blobs, source.id)

    assert stored_files(blob_root) == []
    assert await row_counts(session_factory) == (0, 0, 0)


async def test_oversized_file_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    blob_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = await create_source(session_factory)
    monkeypatch.setattr(files, "MAX_FILE_BYTES", 10)

    with pytest.raises(InvalidInputError, match="File is larger than"):
        await import_file(session_factory, blobs, source.id, b"x" * 11)

    assert stored_files(blob_root) == []
    assert await row_counts(session_factory) == (0, 0, 0)


async def test_database_failure_removes_the_blob_and_all_rows(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    blob_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = await create_source(session_factory)

    async def broken_add(
        self: DocumentProcessingJobRepository, job: DocumentProcessingJob
    ) -> DocumentProcessingJob:
        raise RuntimeError("database is down")

    monkeypatch.setattr(DocumentProcessingJobRepository, "add", broken_add)

    with pytest.raises(RuntimeError, match="database is down"):
        await import_file(session_factory, blobs, source.id)

    assert stored_files(blob_root) == []
    assert await row_counts(session_factory) == (0, 0, 0)


async def test_same_file_can_be_imported_twice(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, blob_root: Path
) -> None:
    source = await create_source(session_factory)

    first = await import_file(session_factory, blobs, source.id)
    second = await import_file(session_factory, blobs, source.id)

    assert first.document.id != second.document.id
    assert first.asset.storage_key != second.asset.storage_key
    assert len(stored_files(blob_root)) == 2
