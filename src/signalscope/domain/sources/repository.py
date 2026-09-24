import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.sources.model import Source


class SourceRepository:
    """Database access for sources.

    It never commits. The caller decides when the transaction ends.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, source: Source) -> Source:
        self.session.add(source)
        # Flush so the database fills in the timestamps and reports errors now.
        await self.session.flush()
        return source

    async def get(self, source_id: uuid.UUID) -> Source | None:
        return await self.session.get(Source, source_id)

    async def list_page(self, limit: int, offset: int) -> list[Source]:
        result = await self.session.scalars(
            select(Source).order_by(Source.created_at, Source.id).limit(limit).offset(offset)
        )
        return list(result.all())

    async def count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Source))
        return result.scalar_one()

    async def delete(self, source_id: uuid.UUID) -> bool:
        """Delete a source. Returns False when there was no source with that ID."""
        result = await self.session.execute(
            delete(Source).where(Source.id == source_id).returning(Source.id)
        )
        return result.scalar_one_or_none() is not None
