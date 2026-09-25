import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunking import TextChunk


class DocumentChunkRepository:
    """Database access for document chunks.

    Chunks are derived from the document content, so they are only replaced
    as a whole. It never commits. The caller decides when the transaction ends.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_document(self, document_id: uuid.UUID) -> list[DocumentChunk]:
        result = await self.session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.position)
        )
        return list(result.all())

    async def replace_for_document(
        self, document_id: uuid.UUID, chunks: Sequence[TextChunk]
    ) -> None:
        """Delete the chunks of a document and add the given ones in their place."""
        await self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        self.session.add_all(
            DocumentChunk(
                document_id=document_id,
                position=chunk.position,
                text=chunk.text,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
                text_hash=chunk.text_hash,
            )
            for chunk in chunks
        )
        await self.session.flush()
