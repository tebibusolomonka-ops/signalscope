import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.cli import cleanup_blobs
from signalscope.core.settings import Settings
from signalscope.domain.blobs.model import BlobCleanupTask
from signalscope.domain.blobs.repository import BlobCleanupTaskRepository
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def settings(database_engine: AsyncEngine, migrated_database: Settings, tmp_path: Path) -> Settings:
    return Settings(database_url=migrated_database.database_url, blob_dir=tmp_path / "blobs")


async def add_task(session_factory: async_sessionmaker[AsyncSession], key: str) -> None:
    async with session_factory() as session:
        await BlobCleanupTaskRepository(session).add(
            key, datetime.now(UTC) - timedelta(minutes=1), "Disk busy."
        )
        await session.commit()


async def run(settings: Settings) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await cleanup_blobs(10, settings, out, err)
    return code, out.getvalue(), err.getvalue()


async def task_count(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(BlobCleanupTask)) or 0


async def test_no_tasks(settings: Settings) -> None:
    assert await run(settings) == (0, "Checked: 0\nDeleted: 0\nFailed: 0\n", "")


async def test_successful_cleanup(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    assert settings.blob_dir is not None
    blobs = LocalBlobStore(settings.blob_dir)
    await blobs.put("ab/orphan", b"left behind")
    await add_task(session_factory, "ab/orphan")
    await add_task(session_factory, "ab/already-gone")

    assert await run(settings) == (0, "Checked: 2\nDeleted: 2\nFailed: 0\n", "")
    assert not await blobs.exists("ab/orphan")
    assert await task_count(session_factory) == 0


async def test_failed_cleanup(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    assert settings.blob_dir is not None
    # A folder where the file should be cannot be deleted as a file.
    (settings.blob_dir / "ab" / "stuck").mkdir(parents=True)
    await add_task(session_factory, "ab/stuck")

    code, out, _ = await run(settings)

    assert (code, out) == (1, "Checked: 1\nDeleted: 0\nFailed: 1\n")
    assert await task_count(session_factory) == 1
