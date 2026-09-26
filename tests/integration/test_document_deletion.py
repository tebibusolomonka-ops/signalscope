import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.core.errors import ConflictError, NotFoundError, ServiceUnavailableError
from signalscope.core.settings import Settings
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.extraction import DocumentExtraction
from signalscope.domain.documents.model import Document
from signalscope.domain.documents.repository import DocumentRepository
from signalscope.domain.documents.service import DocumentService
from signalscope.domain.processing.file_import import FileImportService, ImportedFile
from signalscope.domain.processing.job_repository import DocumentProcessingJobRepository
from signalscope.domain.processing.model import DocumentProcessingJob
from signalscope.domain.processing.processor import DocumentProcessor
from signalscope.domain.sources.model import Source, SourceType
from signalscope.parsing.registry import create_default_parser_registry
from signalscope.storage.blob import BlobStorageError
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio

TEXT = b"Climate policy notes for the harbour city."


class UndeletableBlobStore(LocalBlobStore):
    async def delete(self, key: str) -> None:
        raise BlobStorageError("Could not delete the stored file.")


@pytest.fixture
def blob_root(tmp_path: Path) -> Path:
    return tmp_path / "blobs"


@pytest.fixture
def blobs(blob_root: Path) -> LocalBlobStore:
    return LocalBlobStore(blob_root)


@pytest.fixture
async def source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.commit()
    return source


async def import_file(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    source: Source,
    process: bool = True,
) -> ImportedFile:
    async with session_factory() as session:
        imported = await FileImportService(session, blobs).import_file(
            source.id, filename="notes.txt", content_type="text/plain", data=TEXT
        )
    if process:
        processor = DocumentProcessor(session_factory, blobs, create_default_parser_registry())
        await processor.process(imported.asset.id)
    return imported


async def delete(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore | None,
    document_id: uuid.UUID,
) -> None:
    async with session_factory() as session:
        await DocumentService(session, blobs).delete(document_id)


async def counts(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    models = {
        "documents": Document,
        "assets": DocumentAsset,
        "extractions": DocumentExtraction,
        "chunks": DocumentChunk,
        "jobs": DocumentProcessingJob,
    }
    async with session_factory() as session:
        return {
            name: await session.scalar(select(func.count()).select_from(model)) or 0
            for name, model in models.items()
        }


def stored_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()] if root.exists() else []


async def test_document_without_a_file(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    async with session_factory() as session:
        document = await DocumentRepository(session).add(Document(source_id=source.id))
        await session.commit()

    # No blob store is needed when there is no file.
    await delete(session_factory, None, document.id)

    assert (await counts(session_factory))["documents"] == 0


async def test_processed_document_with_a_file(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    blob_root: Path,
    source: Source,
) -> None:
    imported = await import_file(session_factory, blobs, source)
    before = await counts(session_factory)
    assert before == {"documents": 1, "assets": 1, "extractions": 1, "chunks": 1, "jobs": 1}

    await delete(session_factory, blobs, imported.document.id)

    assert await counts(session_factory) == dict.fromkeys(before, 0)
    assert stored_files(blob_root) == []


async def test_document_waiting_to_be_processed(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    blob_root: Path,
    source: Source,
) -> None:
    imported = await import_file(session_factory, blobs, source, process=False)

    await delete(session_factory, blobs, imported.document.id)

    assert (await counts(session_factory))["jobs"] == 0
    assert stored_files(blob_root) == []


async def test_other_documents_are_kept(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    blob_root: Path,
    source: Source,
) -> None:
    first = await import_file(session_factory, blobs, source)
    async with session_factory() as session:
        second = await FileImportService(session, blobs).import_file(
            source.id, filename="other.txt", content_type="text/plain", data=b"Other text."
        )

    await delete(session_factory, blobs, first.document.id)

    assert (await counts(session_factory))["documents"] == 1
    assert await blobs.exists(second.asset.storage_key)
    assert not await blobs.exists(first.asset.storage_key)


async def test_document_being_processed_is_kept(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    source: Source,
) -> None:
    imported = await import_file(session_factory, blobs, source, process=False)
    async with session_factory() as session:
        await DocumentProcessingJobRepository(session).claim_next(imported.job.available_at)
        await session.commit()

    with pytest.raises(ConflictError, match="Document is being processed"):
        await delete(session_factory, blobs, imported.document.id)

    assert (await counts(session_factory))["documents"] == 1
    assert await blobs.exists(imported.asset.storage_key)


async def test_unknown_document(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    with pytest.raises(NotFoundError, match="Document was not found."):
        await delete(session_factory, blobs, uuid.uuid4())


async def test_file_storage_is_needed_for_a_document_with_a_file(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    source: Source,
) -> None:
    imported = await import_file(session_factory, blobs, source)

    with pytest.raises(ServiceUnavailableError, match="File storage is not configured."):
        await delete(session_factory, None, imported.document.id)

    assert (await counts(session_factory))["documents"] == 1
    assert await blobs.exists(imported.asset.storage_key)


async def test_database_failure_keeps_the_file(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    source: Source,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported = await import_file(session_factory, blobs, source)

    async def broken_delete(self: DocumentRepository, document_id: uuid.UUID) -> bool:
        raise RuntimeError("database is down")

    monkeypatch.setattr(DocumentRepository, "delete", broken_delete)

    with pytest.raises(RuntimeError, match="database is down"):
        await delete(session_factory, blobs, imported.document.id)

    assert await counts(session_factory) == {
        "documents": 1,
        "assets": 1,
        "extractions": 1,
        "chunks": 1,
        "jobs": 1,
    }
    assert await blobs.exists(imported.asset.storage_key)


async def test_failed_file_delete_does_not_undo_the_document_delete(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    blob_root: Path,
    source: Source,
    caplog: pytest.LogCaptureFixture,
) -> None:
    imported = await import_file(session_factory, blobs, source)

    await delete(session_factory, UndeletableBlobStore(blob_root), imported.document.id)

    assert (await counts(session_factory))["documents"] == 0
    assert await blobs.exists(imported.asset.storage_key)
    assert "Could not delete blob" in caplog.text


@pytest.fixture
async def client_with_files(
    session_factory: async_sessionmaker[AsyncSession],
    migrated_database: Settings,
    blob_root: Path,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(database_url=migrated_database.database_url, blob_dir=blob_root))
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_delete_api_removes_an_imported_document(
    client_with_files: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    blob_root: Path,
    source: Source,
) -> None:
    imported = await import_file(session_factory, blobs, source)

    response = await client_with_files.delete(f"/documents/{imported.document.id}")

    assert response.status_code == 204
    assert (await client_with_files.get(f"/documents/{imported.document.id}")).status_code == 404
    assert stored_files(blob_root) == []
