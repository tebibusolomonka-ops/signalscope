import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.blobs.model import BlobCleanupTask
from signalscope.domain.blobs.repository import BlobCleanupTaskRepository
from signalscope.domain.documents.asset_service import DocumentAssetService
from signalscope.domain.documents.model import Document
from signalscope.domain.processing.file_import import FileImportService
from signalscope.domain.processing.job_repository import DocumentProcessingJobRepository
from signalscope.domain.processing.model import DocumentProcessingJob
from signalscope.domain.sources.model import Source, SourceType
from signalscope.storage.blob import BlobStorageError
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
BLOB_KEY = re.compile(r"[0-9a-f]{2}/[0-9a-f]{32}")


class UndeletableBlobStore(LocalBlobStore):
    async def delete(self, key: str) -> None:
        raise BlobStorageError("Could not delete the stored file.")


@pytest.fixture
def blob_root(tmp_path: Path) -> Path:
    return tmp_path / "blobs"


@pytest.fixture
async def source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.commit()
    return source


def break_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the last step of an import fail, after the blob has been written."""

    async def broken_add(
        self: DocumentProcessingJobRepository, job: DocumentProcessingJob
    ) -> DocumentProcessingJob:
        raise RuntimeError("database is down")

    monkeypatch.setattr(DocumentProcessingJobRepository, "add", broken_add)


async def import_file(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    async with session_factory() as session:
        await FileImportService(session, blobs, clock=lambda: NOW).import_file(
            source.id, filename="notes.txt", content_type="text/plain", data=b"Some notes."
        )


async def tasks(session_factory: async_sessionmaker[AsyncSession]) -> list[BlobCleanupTask]:
    async with session_factory() as session:
        return list(await session.scalars(select(BlobCleanupTask)))


def stored_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()] if root.exists() else []


async def test_deleted_blob_needs_no_cleanup_task(
    session_factory: async_sessionmaker[AsyncSession],
    blob_root: Path,
    source: Source,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    break_the_database(monkeypatch)

    with pytest.raises(RuntimeError, match="database is down"):
        await import_file(session_factory, LocalBlobStore(blob_root), source)

    assert stored_files(blob_root) == []
    assert await tasks(session_factory) == []


async def test_blob_that_cannot_be_deleted_is_tracked(
    session_factory: async_sessionmaker[AsyncSession],
    blob_root: Path,
    source: Source,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    break_the_database(monkeypatch)

    with pytest.raises(RuntimeError, match="database is down"):
        await import_file(session_factory, UndeletableBlobStore(blob_root), source)

    [task] = await tasks(session_factory)
    assert BLOB_KEY.fullmatch(task.storage_key)
    assert task.last_error == "Could not delete the stored file."
    assert task.available_at == NOW
    assert task.attempt_count == 0
    # Only the key is stored, never a path on this machine.
    assert str(blob_root) not in task.storage_key
    assert "notes.txt" not in task.storage_key
    # The file is still there, waiting for the cleanup command.
    assert [path.read_bytes() for path in stored_files(blob_root)] == [b"Some notes."]


async def test_failed_import_leaves_no_rows(
    session_factory: async_sessionmaker[AsyncSession],
    blob_root: Path,
    source: Source,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    break_the_database(monkeypatch)

    with pytest.raises(RuntimeError, match="database is down"):
        await import_file(session_factory, UndeletableBlobStore(blob_root), source)

    async with session_factory() as session:
        assert list(await session.scalars(select(Document))) == []


async def test_failed_cleanup_tracking_keeps_the_import_error(
    session_factory: async_sessionmaker[AsyncSession],
    blob_root: Path,
    source: Source,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    break_the_database(monkeypatch)

    async def broken_add(
        self: BlobCleanupTaskRepository, storage_key: str, available_at: datetime, error: str
    ) -> None:
        raise RuntimeError("cleanup table is gone")

    monkeypatch.setattr(BlobCleanupTaskRepository, "add", broken_add)

    with pytest.raises(RuntimeError, match="database is down"):
        await import_file(session_factory, UndeletableBlobStore(blob_root), source)

    assert await tasks(session_factory) == []
    assert "Could not save a cleanup task for blob" in caplog.text


async def test_attaching_a_file_tracks_its_blob_too(
    session_factory: async_sessionmaker[AsyncSession],
    blob_root: Path,
    source: Source,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_factory() as session:
        document = Document(source_id=source.id, title="Report")
        session.add(document)
        await session.commit()

    async def broken_add(self: object, asset: object) -> object:
        raise RuntimeError("database is down")

    monkeypatch.setattr(
        "signalscope.domain.documents.asset_repository.DocumentAssetRepository.add", broken_add
    )

    async with session_factory() as session:
        service = DocumentAssetService(session, UndeletableBlobStore(blob_root), clock=lambda: NOW)
        with pytest.raises(RuntimeError, match="database is down"):
            await service.attach(
                document.id, filename="report.pdf", content_type="application/pdf", data=b"%PDF"
            )

    [task] = await tasks(session_factory)
    assert BLOB_KEY.fullmatch(task.storage_key)
    assert task.available_at == NOW


async def test_repeated_failures_track_each_blob(
    session_factory: async_sessionmaker[AsyncSession],
    blob_root: Path,
    source: Source,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    break_the_database(monkeypatch)
    blobs = UndeletableBlobStore(blob_root)

    for _ in range(2):
        with pytest.raises(RuntimeError, match="database is down"):
            await import_file(session_factory, blobs, source)

    keys = {task.storage_key for task in await tasks(session_factory)}
    assert len(keys) == 2
    assert all(BLOB_KEY.fullmatch(key) for key in keys)


async def test_unknown_source_writes_no_blob(
    session_factory: async_sessionmaker[AsyncSession], blob_root: Path
) -> None:
    blobs = LocalBlobStore(blob_root)

    async with session_factory() as session:
        with pytest.raises(Exception, match="Source was not found."):
            await FileImportService(session, blobs).import_file(
                uuid.uuid4(), filename="a.txt", content_type="text/plain", data=b"x"
            )

    assert stored_files(blob_root) == []
    assert await tasks(session_factory) == []
