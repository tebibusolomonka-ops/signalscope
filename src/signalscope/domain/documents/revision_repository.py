import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.documents.revision import DocumentRevision


class DocumentRevisionRepository:
    """Database access for document revisions.

    The caller decides when a revision is written and with what data. It never
    commits.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_document(self, document_id: uuid.UUID) -> list[DocumentRevision]:
        """Return the revisions of a document, oldest first."""
        result = await self.session.scalars(
            select(DocumentRevision)
            .where(DocumentRevision.document_id == document_id)
            .order_by(DocumentRevision.version)
        )
        return list(result.all())

    async def latest_version(self, document_id: uuid.UUID) -> int:
        """Return the highest version of a document, or 0 when it has no revisions."""
        result = await self.session.scalar(
            select(func.max(DocumentRevision.version)).where(
                DocumentRevision.document_id == document_id
            )
        )
        return result or 0

    async def add_snapshot(
        self,
        document_id: uuid.UUID,
        *,
        version: int,
        title: str | None,
        content: str | None,
        language: str | None,
        url: str | None,
        content_hash: str | None,
        parser_metadata: Mapping[str, Any],
    ) -> DocumentRevision:
        revision = DocumentRevision(
            document_id=document_id,
            version=version,
            title=title,
            content=content,
            language=language,
            url=url,
            content_hash=content_hash,
            parser_metadata=dict(parser_metadata),
        )
        self.session.add(revision)
        # Flush so a version that is already taken fails here.
        await self.session.flush()
        return revision
