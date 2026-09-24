import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.domain.sources.model import Source
from signalscope.domain.sources.repository import SourceRepository
from signalscope.domain.sources.schemas import SourceCreate


class SourceService:
    """Source operations used by the API.

    Writes commit before they return. When a write fails, the session is
    rolled back and the error is raised again.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SourceRepository(session)

    async def create(self, data: SourceCreate) -> Source:
        source = Source(type=data.type, name=data.name, url=data.url)
        try:
            await self.repository.add(source)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return source

    async def get(self, source_id: uuid.UUID) -> Source:
        source = await self.repository.get(source_id)
        if source is None:
            raise NotFoundError("Source was not found.")
        return source

    async def list_page(self, limit: int, offset: int) -> tuple[list[Source], int]:
        """Return one page of sources and the total number of sources."""
        return await self.repository.list_page(limit, offset), await self.repository.count()

    async def delete(self, source_id: uuid.UUID) -> None:
        try:
            deleted = await self.repository.delete(source_id)
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            # A delete can only break the foreign keys from documents and ingestion runs.
            raise ConflictError(
                "Source has documents or ingestion runs and cannot be deleted."
            ) from error
        except Exception:
            await self.session.rollback()
            raise
        if not deleted:
            raise NotFoundError("Source was not found.")
