import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.blobs.model import BlobCleanupTask
from signalscope.domain.blobs.repository import BlobCleanupTaskRepository
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.storage.blob import BlobNotFoundError, BlobStorageError, BlobStore

logger = logging.getLogger(__name__)

# How long a cleanup run holds a task while it deletes the blob.
HOLD_DURATION = timedelta(minutes=5)
FIRST_RETRY_DELAY = timedelta(minutes=1)
MAX_RETRY_DELAY = timedelta(days=1)


def retry_delay(attempt_count: int) -> timedelta:
    """The wait after the given number of failed attempts: 1, 2, 4 minutes and so on."""
    # A cap on the exponent keeps the number small. The delay is capped anyway.
    exponent = min(max(attempt_count - 1, 0), 20)
    return min(FIRST_RETRY_DELAY * (1 << exponent), MAX_RETRY_DELAY)


@dataclass(frozen=True, slots=True)
class CleanupResult:
    checked: int
    deleted: int
    failed: int


class BlobCleanupService:
    """Deletes blobs that were left behind, one cleanup task at a time.

    Tasks are taken in a short transaction. The blobs are deleted with no
    transaction open, and each result is saved in its own short transaction.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        blobs: BlobStore,
        clock: Clock = utc_now,
    ) -> None:
        self.session_factory = session_factory
        self.blobs = blobs
        self.clock = clock

    async def run(self, limit: int) -> CleanupResult:
        tasks = await self._claim(limit)
        deleted = 0
        for task in tasks:
            if await self._clean(task):
                deleted += 1
        return CleanupResult(checked=len(tasks), deleted=deleted, failed=len(tasks) - deleted)

    async def _claim(self, limit: int) -> list[BlobCleanupTask]:
        now = self.clock()
        async with self.session_factory() as session:
            tasks = await BlobCleanupTaskRepository(session).claim_due(
                now, now + HOLD_DURATION, limit
            )
            await session.commit()
        return tasks

    async def _clean(self, task: BlobCleanupTask) -> bool:
        try:
            await self.blobs.delete(task.storage_key)
        except BlobNotFoundError:
            # The blob is already gone, which is what the task wanted.
            pass
        except BlobStorageError as error:
            logger.warning("Could not delete blob %s", task.storage_key, exc_info=True)
            await self._record_failure(task, str(error), self.clock())
            return False
        async with self.session_factory() as session:
            await BlobCleanupTaskRepository(session).delete(task.id)
            await session.commit()
        return True

    async def _record_failure(self, task: BlobCleanupTask, error: str, now: datetime) -> None:
        available_at = now + retry_delay(task.attempt_count + 1)
        async with self.session_factory() as session:
            await BlobCleanupTaskRepository(session).record_failure(task.id, error, available_at)
            await session.commit()
