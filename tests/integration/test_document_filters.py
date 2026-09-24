from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.model import Document
from signalscope.domain.documents.repository import DocumentFilters, DocumentRepository
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

MARCH_1 = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
MARCH_2 = datetime(2026, 3, 2, 10, 0, tzinfo=UTC)
MARCH_3 = datetime(2026, 3, 3, 10, 0, tzinfo=UTC)


@pytest.fixture
async def sources(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, Source]:
    """Two sources with four documents: A1, A2 and A3 in source A, B1 in source B."""
    async with session_factory() as session:
        source_a = Source(type=SourceType.RSS, name="Feed A", url="https://a.example.com/rss")
        source_b = Source(type=SourceType.RSS, name="Feed B", url="https://b.example.com/rss")
        session.add_all([source_a, source_b])
        await session.flush()
        session.add_all(
            [
                Document(source_id=source_a.id, title="A1", language="en", published_at=MARCH_1),
                Document(source_id=source_a.id, title="A2", language="de", published_at=MARCH_2),
                Document(source_id=source_a.id, title="A3", language="en", published_at=None),
                Document(source_id=source_b.id, title="B1", language="en", published_at=MARCH_3),
            ]
        )
        await session.commit()
    return {"a": source_a, "b": source_b}


async def titles(
    session_factory: async_sessionmaker[AsyncSession], filters: DocumentFilters
) -> set[str | None]:
    async with session_factory() as session:
        documents = await DocumentRepository(session).list_all(filters)
    return {document.title for document in documents}


async def test_no_filters_returns_everything(
    session_factory: async_sessionmaker[AsyncSession], sources: dict[str, Source]
) -> None:
    assert await titles(session_factory, DocumentFilters()) == {"A1", "A2", "A3", "B1"}


async def test_source_filter(
    session_factory: async_sessionmaker[AsyncSession], sources: dict[str, Source]
) -> None:
    filters = DocumentFilters(source_id=sources["a"].id)

    assert await titles(session_factory, filters) == {"A1", "A2", "A3"}


async def test_language_filter(
    session_factory: async_sessionmaker[AsyncSession], sources: dict[str, Source]
) -> None:
    assert await titles(session_factory, DocumentFilters(language="en")) == {"A1", "A3", "B1"}


async def test_published_from_includes_the_boundary(
    session_factory: async_sessionmaker[AsyncSession], sources: dict[str, Source]
) -> None:
    assert await titles(session_factory, DocumentFilters(published_from=MARCH_2)) == {"A2", "B1"}


async def test_published_to_includes_the_boundary(
    session_factory: async_sessionmaker[AsyncSession], sources: dict[str, Source]
) -> None:
    assert await titles(session_factory, DocumentFilters(published_to=MARCH_2)) == {"A1", "A2"}


async def test_date_range(
    session_factory: async_sessionmaker[AsyncSession], sources: dict[str, Source]
) -> None:
    filters = DocumentFilters(
        published_from=MARCH_1 + timedelta(hours=1), published_to=MARCH_3 - timedelta(hours=1)
    )

    assert await titles(session_factory, filters) == {"A2"}


async def test_dates_with_other_offsets_compare_as_the_same_instant(
    session_factory: async_sessionmaker[AsyncSession], sources: dict[str, Source]
) -> None:
    # 12:00 at UTC+2 is 10:00 UTC, the exact time of A1.
    march_1_in_cairo = datetime(2026, 3, 1, 12, 0, tzinfo=timezone(timedelta(hours=2)))

    assert await titles(session_factory, DocumentFilters(published_to=march_1_in_cairo)) == {"A1"}


async def test_combined_filters(
    session_factory: async_sessionmaker[AsyncSession], sources: dict[str, Source]
) -> None:
    source_a = sources["a"].id

    assert await titles(session_factory, DocumentFilters(source_id=source_a, language="en")) == {
        "A1",
        "A3",
    }
    assert await titles(
        session_factory, DocumentFilters(source_id=source_a, published_from=MARCH_1)
    ) == {"A1", "A2"}


async def test_no_matches(
    session_factory: async_sessionmaker[AsyncSession], sources: dict[str, Source]
) -> None:
    assert await titles(session_factory, DocumentFilters(language="fr")) == set()
    assert (
        await titles(session_factory, DocumentFilters(source_id=sources["b"].id, language="de"))
        == set()
    )
