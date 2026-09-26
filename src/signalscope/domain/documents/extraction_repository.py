import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.documents.extraction import DocumentExtraction


class DocumentExtractionRepository:
    """Database access for document extractions.

    It never commits. The caller decides when the transaction ends.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, extraction: DocumentExtraction) -> DocumentExtraction:
        """Add a new extraction, or flush the changes of one already loaded."""
        self.session.add(extraction)
        await self.session.flush()
        return extraction

    async def get_by_document(self, document_id: uuid.UUID) -> DocumentExtraction | None:
        result = await self.session.scalars(
            select(DocumentExtraction).where(DocumentExtraction.document_id == document_id)
        )
        return result.one_or_none()

    async def delete_for_document(self, document_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(DocumentExtraction).where(DocumentExtraction.document_id == document_id)
        )
