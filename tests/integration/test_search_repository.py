import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import chunk_text
from signalscope.domain.documents.model import Document
from signalscope.domain.search.repository import SearchRepository, SearchResult
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio


async def create_source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.commit()
    return source


async def add_document(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    content: str,
    title: str | None = None,
    url: str | None = None,
) -> Document:
    async with session_factory() as session:
        document = Document(source_id=source.id, title=title, url=url, content=content)
        session.add(document)
        await session.flush()
        await DocumentChunkRepository(session).replace_for_document(
            document.id, chunk_text(content)
        )
        await session.commit()
    return document


async def search(
    session_factory: async_sessionmaker[AsyncSession],
    query: str,
    limit: int = 10,
    source_id: uuid.UUID | None = None,
) -> list[SearchResult]:
    async with session_factory() as session:
        return await SearchRepository(session).search(query, limit=limit, source_id=source_id)


async def test_matching_word(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory)
    match = await add_document(
        session_factory,
        source,
        "New rules for coastal climate adaptation.",
        title="Coastal rules",
        url="https://example.com/rules",
    )
    await add_document(session_factory, source, "The budget for the second quarter.")

    [result] = await search(session_factory, "climate")

    assert result.document_id == match.id
    assert result.source_id == source.id
    assert (result.title, result.url) == ("Coastal rules", "https://example.com/rules")
    assert "climate" in result.excerpt
    assert result.rank > 0


async def test_excerpt_is_plain_text(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory)
    await add_document(session_factory, source, "Climate <script>alert(1)</script> policy.")

    [result] = await search(session_factory, "climate")

    assert "<b>" not in result.excerpt
    assert result.excerpt.startswith("Climate")


async def test_excerpt_is_short(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory)
    # About 600 characters, so the text stays in one chunk.
    words = " ".join(f"word{number}" for number in range(50))
    await add_document(session_factory, source, f"{words} climate {words}")

    [result] = await search(session_factory, "climate")

    assert "climate" in result.excerpt
    assert len(result.excerpt.split()) <= 35


async def test_all_terms_must_match(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory)
    both = await add_document(session_factory, source, "Climate policy for cities.")
    await add_document(session_factory, source, "Climate data only.")
    await add_document(session_factory, source, "Policy notes only.")

    results = await search(session_factory, "climate policy")

    assert [result.document_id for result in results] == [both.id]


async def test_or_and_phrase_queries(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory)
    climate = await add_document(session_factory, source, "Climate policy for cities.")
    budget = await add_document(session_factory, source, "Budget policy for towns.")

    either = await search(session_factory, "climate or budget")
    phrase = await search(session_factory, '"policy for cities"')

    assert {result.document_id for result in either} == {climate.id, budget.id}
    assert [result.document_id for result in phrase] == [climate.id]


async def test_better_matches_rank_higher(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory)
    filler = " ".join(["other"] * 60)
    weak = await add_document(session_factory, source, f"Climate. {filler} Policy.")
    strong = await add_document(
        session_factory, source, "Climate policy. Climate policy again. Climate policy."
    )

    results = await search(session_factory, "climate policy")

    assert [result.document_id for result in results] == [strong.id, weak.id]
    assert results[0].rank > results[1].rank


async def test_no_match(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory)
    await add_document(session_factory, source, "Climate policy for cities.")

    assert await search(session_factory, "volcano") == []


@pytest.mark.parametrize("query", ["", "   ", "!!!", "- ,"])
async def test_query_without_words_matches_nothing(
    session_factory: async_sessionmaker[AsyncSession], query: str
) -> None:
    source = await create_source(session_factory)
    await add_document(session_factory, source, "Climate policy for cities.")

    assert await search(session_factory, query) == []


async def test_source_filter(session_factory: async_sessionmaker[AsyncSession]) -> None:
    first = await create_source(session_factory)
    second = await create_source(session_factory)
    await add_document(session_factory, first, "Climate report one.")
    in_second = await add_document(session_factory, second, "Climate report two.")

    results = await search(session_factory, "climate", source_id=second.id)

    assert [result.document_id for result in results] == [in_second.id]
    assert await search(session_factory, "climate", source_id=uuid.uuid4()) == []


async def test_limit(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory)
    for number in range(5):
        await add_document(session_factory, source, f"Climate report number {number}.")

    assert len(await search(session_factory, "climate", limit=3)) == 3
    assert len(await search(session_factory, "climate", limit=50)) == 5


@pytest.mark.parametrize("limit", [0, 51, -1])
async def test_limit_is_bounded(
    session_factory: async_sessionmaker[AsyncSession], limit: int
) -> None:
    with pytest.raises(ValueError, match="between 1 and 50"):
        await search(session_factory, "climate", limit=limit)


async def test_equal_ranks_have_a_stable_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory)
    for _ in range(4):
        await add_document(session_factory, source, "Climate report.")

    first = await search(session_factory, "climate")
    second = await search(session_factory, "climate")

    assert [result.chunk_id for result in first] == [result.chunk_id for result in second]
    assert [result.document_id for result in first] == sorted(
        result.document_id for result in first
    )


async def test_unicode_and_punctuation(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory)
    german = await add_document(session_factory, source, "Klimapolitik für Städte, kurz erklärt.")
    await add_document(session_factory, source, "Climate policy for cities.")

    for query in ["Städte", "STÄDTE!", "städte, klimapolitik"]:
        results = await search(session_factory, query)
        assert [result.document_id for result in results] == [german.id], query
