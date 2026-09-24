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

    async def list_all(self) -> list[Source]:
        return await self.repository.list_all()

    async def delete(self, source_id: uuid.UUID) -> None:
        try:
            deleted = await self.repository.delete(source_id)
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            # The documents foreign key is the only rule a delete can break.
            raise ConflictError("Source has documents and cannot be deleted.") from error
        except Exception:
            await self.session.rollback()
            raise
        if not deleted:
            raise NotFoundError("Source was not found.")
