import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import NotFoundError
from signalscope.domain.documents.repository import DocumentRepository
from signalscope.domain.documents.revision import DocumentRevision
from signalscope.domain.documents.revision_repository import DocumentRevisionRepository


class DocumentRevisionService:
    """Reads the history of a document. Revisions are only written by processing."""

    def __init__(self, session: AsyncSession) -> None:
        self.documents = DocumentRepository(session)
        self.revisions = DocumentRevisionRepository(session)

    async def list(self, document_id: uuid.UUID) -> list[DocumentRevision]:
        await self._check_document(document_id)
        return await self.revisions.list_by_document(document_id)

    async def get(self, document_id: uuid.UUID, version: int) -> DocumentRevision:
        await self._check_document(document_id)
        revision = await self.revisions.get(document_id, version)
        if revision is None:
            raise NotFoundError("Document revision was not found.")
        return revision

    async def _check_document(self, document_id: uuid.UUID) -> None:
        if await self.documents.get(document_id) is None:
            raise NotFoundError("Document was not found.")
