import uuid
from collections.abc import Sequence

from sqlalchemy import delete, literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunking import TextChunk

# A place in the stable order of all chunks: (document ID, position).
ChunkKey = tuple[uuid.UUID, int]


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
                chunk_metadata=dict(chunk.metadata),
            )
            for chunk in chunks
        )
        await self.session.flush()

    async def page(
        self, after: ChunkKey | None, size: int, document_id: uuid.UUID | None = None
    ) -> list[tuple[uuid.UUID, uuid.UUID, int]]:
        """Return up to size (chunk ID, document ID, position) rows after the given key.

        Rows come in (document, position) order, so paging with the last key of
        each page walks through all chunks once without loading them all.
        """
        statement = select(DocumentChunk.id, DocumentChunk.document_id, DocumentChunk.position)
        if document_id is not None:
            statement = statement.where(DocumentChunk.document_id == document_id)
        if after is not None:
            statement = statement.where(
                tuple_(DocumentChunk.document_id, DocumentChunk.position)
                > tuple_(literal(after[0]), literal(after[1]))
            )
        rows = await self.session.execute(
            statement.order_by(DocumentChunk.document_id, DocumentChunk.position).limit(size)
        )
        return [(chunk_id, document, position) for chunk_id, document, position in rows]
