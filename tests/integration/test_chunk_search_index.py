import hashlib

import pytest
from sqlalchemy import Select, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk import (
    DocumentChunk,
    chunk_search_vector,
    text_search_config,
)
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

TEXTS = [
    "Climate policy for coastal cities.",
    "Klimapolitik für Städte und Gemeinden.",
    "Budget report for the second quarter.",
]


async def add_chunks(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, content="\n".join(TEXTS))
        session.add(document)
        await session.flush()
        start = 0
        for position, chunk in enumerate(TEXTS):
            session.add(
                DocumentChunk(
                    document_id=document.id,
                    position=position,
                    text=chunk,
                    start_char=start,
                    end_char=start + len(chunk),
                    text_hash=hashlib.sha256(chunk.encode()).hexdigest(),
                )
            )
            start += len(chunk) + 1
        await session.commit()


def matching(query: str) -> Select[tuple[str]]:
    return select(DocumentChunk.text).where(
        chunk_search_vector().bool_op("@@")(func.websearch_to_tsquery(text_search_config(), query))
    )


async def search(session_factory: async_sessionmaker[AsyncSession], query: str) -> list[str]:
    async with session_factory() as session:
        return list(await session.scalars(matching(query).order_by(DocumentChunk.position)))


async def test_index_exists(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        definition = await session.scalar(
            text(
                "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_document_chunks_text_search'"
            )
        )

    assert definition is not None
    assert "USING gin (to_tsvector('simple'::regconfig, text))" in definition


async def test_search_query_uses_the_index(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_chunks(session_factory)
    sql = str(
        matching("climate").compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    async with session_factory() as session:
        # With so few rows PostgreSQL would scan the table, so that is turned off.
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(await session.scalars(text(f"EXPLAIN {sql}")))

    assert "ix_document_chunks_text_search" in plan


async def test_words_match_without_case_or_language(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_chunks(session_factory)

    assert await search(session_factory, "CLIMATE") == [TEXTS[0]]
    assert await search(session_factory, "städte") == [TEXTS[1]]
    assert await search(session_factory, "budget quarter") == [TEXTS[2]]
    assert await search(session_factory, "volcano") == []
