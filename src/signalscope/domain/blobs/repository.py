from datetime import datetime

from sqlalchemy import select
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
