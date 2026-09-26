import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.documents.chunk import (
    DocumentChunk,
    chunk_search_vector,
    text_search_config,
)
from signalscope.domain.documents.model import Document

MAX_SEARCH_LIMIT = 50
# No highlight markers, so an excerpt is plain text and safe to show anywhere.
HEADLINE_OPTIONS = 'StartSel="", StopSel="", MaxWords=35, MinWords=15'


@dataclass(frozen=True, slots=True)
class SearchResult:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    source_id: uuid.UUID
    title: str | None
    url: str | None
    excerpt: str
    rank: float
    # Where the chunk came from, such as {"page_number": 3}.
    chunk_metadata: dict[str, Any]


class SearchRepository:
    """Full text search over document chunks with PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self, query: str, *, limit: int, source_id: uuid.UUID | None = None
    ) -> list[SearchResult]:
        """Return the chunks that match query, best match first.

        The query uses web search syntax: words must all appear, "quoted
        phrases" match in order, "or" gives alternatives and -word excludes a
        word. A query without any words matches nothing.
        """
        if not 1 <= limit <= MAX_SEARCH_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}")
        tsquery = func.websearch_to_tsquery(text_search_config(), query)
        rank = func.ts_rank_cd(chunk_search_vector(), tsquery)
        statement = (
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                Document.source_id,
                Document.title,
                Document.url,
                func.ts_headline(
                    text_search_config(), DocumentChunk.text, tsquery, HEADLINE_OPTIONS
                ),
                rank,
                DocumentChunk.chunk_metadata,
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(chunk_search_vector().bool_op("@@")(tsquery))
            # Chunks with the same rank keep the order they have in their documents.
            .order_by(rank.desc(), DocumentChunk.document_id, DocumentChunk.position)
            .limit(limit)
        )
        if source_id is not None:
            statement = statement.where(Document.source_id == source_id)
        rows = await self.session.execute(statement)
        return [
            SearchResult(
                chunk_id=chunk_id,
                document_id=document_id,
                source_id=row_source_id,
                title=title,
                url=url,
                excerpt=excerpt,
                rank=float(row_rank),
                chunk_metadata=dict(metadata),
            )
            for (
                chunk_id,
                document_id,
                row_source_id,
                title,
                url,
                excerpt,
                row_rank,
                metadata,
            ) in rows
        ]
