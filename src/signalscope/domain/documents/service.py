import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.db.errors import is_unique_violation
from signalscope.domain.documents.model import Document
from signalscope.domain.documents.repository import DocumentFilters, DocumentRepository
from signalscope.domain.documents.schemas import DocumentCreate
from signalscope.domain.sources.repository import SourceRepository


class DocumentService:
    """Document operations used by the API.

    Writes commit before they return. When a write fails, the session is
    rolled back and the error is raised again.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.documents = DocumentRepository(session)
        self.sources = SourceRepository(session)

    async def create(self, data: DocumentCreate) -> Document:
        if await self.sources.get(data.source_id) is None:
            raise NotFoundError("Source was not found.")
        document = Document(**data.model_dump())
        try:
            await self.documents.add(document)
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            if is_unique_violation(error):
                raise ConflictError("Document already exists for this source.") from error
            raise
        except Exception:
            await self.session.rollback()
            raise
        return document

    async def get(self, document_id: uuid.UUID) -> Document:
        document = await self.documents.get(document_id)
        if document is None:
            raise NotFoundError("Document was not found.")
        return document

    async def list_page(
        self, filters: DocumentFilters, limit: int, offset: int
    ) -> tuple[list[Document], int]:
        """Return one page of matching documents and the total number that match."""
        items = await self.documents.list_page(filters, limit, offset)
        return items, await self.documents.count(filters)

    async def delete(self, document_id: uuid.UUID) -> None:
        try:
            deleted = await self.documents.delete(document_id)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        if not deleted:
            raise NotFoundError("Document was not found.")
