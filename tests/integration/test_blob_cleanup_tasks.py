from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.blobs.model import BlobCleanupTask
from signalscope.domain.blobs.repository import BlobCleanupTaskRepository
from signalscope.domain.documents.service import DocumentService
from signalscope.domain.processing.file_import import FileImportService
from signalscope.domain.sources.model import Source, SourceType
from signalscope.storage.blob import BlobStorageError
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


class UndeletableBlobStore(LocalBlobStore):
    async def delete(self, key: str) -> None:
        raise BlobStorageError("Could not delete the stored file.")


async def add_task(
    session_factory: async_sessionmaker[AsyncSession], key: str, error: str = "Disk busy."
) -> None:
    async with session_factory() as session:
        await BlobCleanupTaskRepository(session).add(key, NOW, error)
        await session.commit()


async def tasks(session_factory: async_sessionmaker[AsyncSession]) -> list[BlobCleanupTask]:
    async with session_factory() as session:
        return list(await session.scalars(select(BlobCleanupTask)))


async def test_task_is_saved(session_factory: async_sessionmaker[AsyncSession]) -> None:
    await add_task(session_factory, "ab/abc123")

    [task] = await tasks(session_factory)
    assert task.storage_key == "ab/abc123"
    assert task.attempt_count == 0
    assert task.available_at == NOW
    assert task.last_error == "Disk busy."


async def test_same_key_is_tracked_once(session_factory: async_sessionmaker[AsyncSession]) -> None:
    await add_task(session_factory, "ab/abc123", "First error.")
    await add_task(session_factory, "ab/abc123", "Second error.")

    [task] = await tasks(session_factory)
    assert task.last_error == "First error."


async def test_database_keeps_keys_unique(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all(
            [
                BlobCleanupTask(storage_key="ab/same", available_at=NOW),
                BlobCleanupTask(storage_key="ab/same", available_at=NOW),
            ]
        )
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_attempt_count_cannot_be_negative(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(BlobCleanupTask(storage_key="ab/key", available_at=NOW, attempt_count=-1))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_database_defaults(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "INSERT INTO blob_cleanup_tasks (id, storage_key) "
                    "VALUES (gen_random_uuid(), 'ab/key') "
                    "RETURNING attempt_count, available_at IS NOT NULL"
                )
            )
        ).one()

    assert tuple(row) == (0, True)


async def test_failed_file_delete_creates_a_task(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    blobs = LocalBlobStore(tmp_path / "blobs")
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.commit()
        imported = await FileImportService(session, blobs).import_file(
            source.id, filename="notes.txt", content_type="text/plain", data=b"hello"
        )

    async with session_factory() as session:
        await DocumentService(
            session, UndeletableBlobStore(tmp_path / "blobs"), clock=lambda: NOW
        ).delete(imported.document.id)

    [task] = await tasks(session_factory)
    assert task.storage_key == imported.asset.storage_key
    assert task.last_error == "Could not delete the stored file."
    assert task.available_at == NOW
    # Only the key is kept, never a path on the disk.
    assert str(tmp_path) not in task.storage_key
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(BlobCleanupTask)) == 1


async def test_successful_file_delete_creates_no_task(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    blobs = LocalBlobStore(tmp_path / "blobs")
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.commit()
        imported = await FileImportService(session, blobs).import_file(
            source.id, filename="notes.txt", content_type="text/plain", data=b"hello"
        )

    async with session_factory() as session:
        await DocumentService(session, blobs).delete(imported.document.id)

    assert await tasks(session_factory) == []


async def test_repository_does_not_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await BlobCleanupTaskRepository(session).add("ab/key", NOW + timedelta(hours=1), "x")

    assert await tasks(session_factory) == []
