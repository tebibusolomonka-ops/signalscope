from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.model import Document
from signalscope.domain.documents.repository import DocumentRepository
from signalscope.domain.ingestion.duplicates import Duplicate, DuplicateReason, find_duplicate
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

HASH_A = "a" * 64
HASH_B = "b" * 64


@dataclass
class Existing:
    source: Source
    other_source: Source
    document: Document
    url_only: Document


@pytest.fixture
async def existing(session_factory: async_sessionmaker[AsyncSession]) -> Existing:
    """Source "a" has a document with every identifier set and one with only a URL."""
    async with session_factory() as session:
        source = Source(type=SourceType.RSS, name="Feed A", url="https://a.example/rss")
        other_source = Source(type=SourceType.RSS, name="Feed B", url="https://b.example/rss")
        session.add_all([source, other_source])
        await session.flush()
        document = Document(
            source_id=source.id,
            external_id="guid-1",
            url="https://a.example/1",
            content_hash=HASH_A,
        )
        url_only = Document(source_id=source.id, url="https://a.example/2")
        session.add_all([document, url_only])
        await session.commit()
    return Existing(source, other_source, document, url_only)


async def check(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    *,
    external_id: str | None = None,
    url: str | None = None,
    content_hash: str | None = None,
) -> Duplicate | None:
    async with session_factory() as session:
        return await find_duplicate(
            DocumentRepository(session),
            source.id,
            external_id=external_id,
            url=url,
            content_hash=content_hash,
        )


async def test_same_external_id_is_a_duplicate(
    session_factory: async_sessionmaker[AsyncSession], existing: Existing
) -> None:
    duplicate = await check(session_factory, existing.source, external_id="guid-1")

    assert duplicate is not None
    assert duplicate.reason is DuplicateReason.EXTERNAL_ID
    assert duplicate.document.id == existing.document.id


async def test_same_url_is_a_duplicate(
    session_factory: async_sessionmaker[AsyncSession], existing: Existing
) -> None:
    duplicate = await check(
        session_factory, existing.source, external_id="guid-new", url="https://a.example/2"
    )

    assert duplicate is not None
    assert duplicate.reason is DuplicateReason.URL
    assert duplicate.document.id == existing.url_only.id


async def test_same_content_is_a_duplicate(
    session_factory: async_sessionmaker[AsyncSession], existing: Existing
) -> None:
    duplicate = await check(
        session_factory,
        existing.source,
        external_id="guid-new",
        url="https://a.example/new",
        content_hash=HASH_A,
    )

    assert duplicate is not None
    assert duplicate.reason is DuplicateReason.CONTENT
    assert duplicate.document.id == existing.document.id


async def test_external_id_is_checked_first(
    session_factory: async_sessionmaker[AsyncSession], existing: Existing
) -> None:
    duplicate = await check(
        session_factory,
        existing.source,
        external_id="guid-1",
        url="https://a.example/2",
        content_hash=HASH_A,
    )

    assert duplicate is not None
    assert duplicate.reason is DuplicateReason.EXTERNAL_ID


async def test_other_sources_are_not_checked(
    session_factory: async_sessionmaker[AsyncSession], existing: Existing
) -> None:
    duplicate = await check(
        session_factory,
        existing.other_source,
        external_id="guid-1",
        url="https://a.example/1",
        content_hash=HASH_A,
    )

    assert duplicate is None


async def test_new_item_is_not_a_duplicate(
    session_factory: async_sessionmaker[AsyncSession], existing: Existing
) -> None:
    duplicate = await check(
        session_factory,
        existing.source,
        external_id="guid-new",
        url="https://a.example/new",
        content_hash=HASH_B,
    )

    assert duplicate is None


async def test_missing_values_are_skipped(
    session_factory: async_sessionmaker[AsyncSession], existing: Existing
) -> None:
    # url_only has no external ID or hash, so an item without them must not match it.
    assert await check(session_factory, existing.source) is None
    assert await check(session_factory, existing.source, url="https://a.example/new") is None
