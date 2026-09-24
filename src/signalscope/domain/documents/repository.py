import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.documents.model import Document


class DocumentRepository:
    """Database access for documents.

    It never commits. The caller decides when the transaction ends.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, document: Document) -> Document:
        self.session.add(document)
        # Flush so the database fills in the timestamps and reports errors now.
        await self.session.flush()
        return document

    async def get(self, document_id: uuid.UUID) -> Document | None:
        return await self.session.get(Document, document_id)

    async def list_all(self) -> list[Document]:
        result = await self.session.scalars(
            select(Document).order_by(Document.created_at, Document.id)
        )
        return list(result.all())

    async def delete(self, document_id: uuid.UUID) -> bool:
        """Delete a document. Returns False when there was no document with that ID."""
        result = await self.session.execute(
            delete(Document).where(Document.id == document_id).returning(Document.id)
        )
        return result.scalar_one_or_none() is not None
