from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.blobs.cleanup import BlobCleanupService, CleanupResult
from signalscope.domain.blobs.model import BlobCleanupTask
from signalscope.domain.blobs.repository import BlobCleanupTaskRepository
from signalscope.storage.blob import BlobNotFoundError, BlobStorageError
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


class FailingBlobStore(LocalBlobStore):
    async def delete(self, key: str) -> None:
        raise BlobStorageError("Could not delete the stored file.")


class StrictBlobStore(LocalBlobStore):
    """A store that reports missing blobs, as some stores do."""

    async def delete(self, key: str) -> None:
        if not await self.exists(key):
            raise BlobNotFoundError()
        await super().delete(key)


@pytest.fixture
def blobs(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(tmp_path / "blobs")


async def add_task(
    session_factory: async_sessionmaker[AsyncSession],
    key: str,
    available_at: datetime = NOW - timedelta(minutes=1),
) -> None:
    async with session_factory() as session:
        await BlobCleanupTaskRepository(session).add(key, available_at, "Disk busy.")
        await session.commit()


async def tasks(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, BlobCleanupTask]:
    async with session_factory() as session:
        rows = await session.scalars(select(BlobCleanupTask))
        return {task.storage_key: task for task in rows}


async def run(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, limit: int = 10
) -> CleanupResult:
    return await BlobCleanupService(session_factory, blobs, clock=lambda: NOW).run(limit)


async def test_no_tasks(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    assert await run(session_factory, blobs) == CleanupResult(checked=0, deleted=0, failed=0)


async def test_blob_is_deleted_and_the_task_removed(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    await blobs.put("ab/orphan", b"left behind")
    await add_task(session_factory, "ab/orphan")

    result = await run(session_factory, blobs)

    assert result == CleanupResult(checked=1, deleted=1, failed=0)
    assert not await blobs.exists("ab/orphan")
    assert await tasks(session_factory) == {}


@pytest.mark.parametrize("store_type", [LocalBlobStore, StrictBlobStore])
async def test_missing_blob_counts_as_deleted(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    store_type: type[LocalBlobStore],
) -> None:
    await add_task(session_factory, "ab/already-gone")

    result = await run(session_factory, store_type(tmp_path / "blobs"))

    assert result == CleanupResult(checked=1, deleted=1, failed=0)
    assert await tasks(session_factory) == {}


async def test_failure_is_tried_again_later(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await add_task(session_factory, "ab/stuck")

    result = await run(session_factory, FailingBlobStore(tmp_path / "blobs"))

    assert result == CleanupResult(checked=1, deleted=0, failed=1)
    task = (await tasks(session_factory))["ab/stuck"]
    assert task.attempt_count == 1
    assert task.last_error == "Could not delete the stored file."
    assert task.available_at == NOW + timedelta(minutes=1)


async def test_retry_delay_grows_with_each_failure(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await add_task(session_factory, "ab/stuck")
    store = FailingBlobStore(tmp_path / "blobs")
    now = NOW
    delays = []
    for _ in range(3):
        await BlobCleanupService(session_factory, store, clock=lambda at=now: at).run(10)
        task = (await tasks(session_factory))["ab/stuck"]
        delays.append(task.available_at - now)
        now = task.available_at

    assert delays == [timedelta(minutes=1), timedelta(minutes=2), timedelta(minutes=4)]
    assert task.attempt_count == 3


async def test_tasks_that_are_not_due_wait(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    await blobs.put("ab/later", b"x")
    await add_task(session_factory, "ab/later", available_at=NOW + timedelta(minutes=1))

    assert await run(session_factory, blobs) == CleanupResult(checked=0, deleted=0, failed=0)
    assert await blobs.exists("ab/later")


async def test_limit(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    for number in range(3):
        await add_task(session_factory, f"ab/orphan{number}")

    assert (await run(session_factory, blobs, limit=2)).checked == 2
    assert len(await tasks(session_factory)) == 1


async def test_held_task_is_not_taken_twice(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_task(session_factory, "ab/orphan")

    async with session_factory() as session:
        first = await BlobCleanupTaskRepository(session).claim_due(
            NOW, NOW + timedelta(minutes=5), 10
        )
        await session.commit()
    async with session_factory() as session:
        second = await BlobCleanupTaskRepository(session).claim_due(
            NOW, NOW + timedelta(minutes=5), 10
        )

    assert [task.storage_key for task in first] == ["ab/orphan"]
    assert second == []
