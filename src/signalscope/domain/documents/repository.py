import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.documents.model import Document


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentFilters:
    """Optional conditions for listing documents. Date limits are inclusive."""

    source_id: uuid.UUID | None = None
    language: str | None = None
    published_from: datetime | None = None
    published_to: datetime | None = None


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

    async def list_all(self, filters: DocumentFilters) -> list[Document]:
        result = await self.session.scalars(
            select(Document).where(*_conditions(filters)).order_by(Document.created_at, Document.id)
        )
        return list(result.all())

    async def delete(self, document_id: uuid.UUID) -> bool:
        """Delete a document. Returns False when there was no document with that ID."""
        result = await self.session.execute(
            delete(Document).where(Document.id == document_id).returning(Document.id)
        )
        return result.scalar_one_or_none() is not None


def _conditions(filters: DocumentFilters) -> list[ColumnElement[bool]]:
    # Rows without published_at never match a date limit, because NULL comparisons are false.
    conditions: list[ColumnElement[bool]] = []
    if filters.source_id is not None:
        conditions.append(Document.source_id == filters.source_id)
    if filters.language is not None:
        conditions.append(Document.language == filters.language)
    if filters.published_from is not None:
        conditions.append(Document.published_at >= filters.published_from)
    if filters.published_to is not None:
        conditions.append(Document.published_at <= filters.published_to)
    return conditions
