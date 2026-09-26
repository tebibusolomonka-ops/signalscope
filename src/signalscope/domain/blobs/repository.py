import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import short_error_message
from signalscope.domain.blobs.model import BlobCleanupTask


class BlobCleanupTaskRepository:
    """Database access for blob cleanup tasks.

    It never commits. The caller decides when the transaction ends.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, storage_key: str, available_at: datetime, error: str) -> None:
        """Record that a blob still needs to be deleted.

        A key that already has a task keeps its task as it is.
        """
        await self.session.execute(
            insert(BlobCleanupTask)
            .values(
                storage_key=storage_key,
                available_at=available_at,
                last_error=short_error_message(error),
            )
            .on_conflict_do_nothing(index_elements=[BlobCleanupTask.storage_key])
        )

    async def get_by_key(self, storage_key: str) -> BlobCleanupTask | None:
        result = await self.session.scalars(
            select(BlobCleanupTask).where(BlobCleanupTask.storage_key == storage_key)
        )
        return result.one_or_none()

    async def claim_due(
        self, now: datetime, hold_until: datetime, limit: int
    ) -> list[BlobCleanupTask]:
        """Take up to limit tasks that are due and hold them until hold_until.

        Holding a task moves its available_at forward, so another cleanup run
        leaves it alone while this one deletes the blob. Rows locked by another
        transaction are skipped.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        result = await self.session.scalars(
            select(BlobCleanupTask)
            .where(BlobCleanupTask.available_at <= now)
            .order_by(BlobCleanupTask.available_at, BlobCleanupTask.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        tasks = list(result.all())
        for task in tasks:
            task.available_at = hold_until
        await self.session.flush()
        return tasks

    async def delete(self, task_id: uuid.UUID) -> None:
        await self.session.execute(delete(BlobCleanupTask).where(BlobCleanupTask.id == task_id))

    async def record_failure(self, task_id: uuid.UUID, error: str, available_at: datetime) -> None:
        await self.session.execute(
            update(BlobCleanupTask)
            .where(BlobCleanupTask.id == task_id)
            .values(
                attempt_count=BlobCleanupTask.attempt_count + 1,
                last_error=short_error_message(error),
                available_at=available_at,
            )
        )
