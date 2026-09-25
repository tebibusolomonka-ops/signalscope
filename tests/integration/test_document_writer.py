import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.fingerprint import content_fingerprint
from signalscope.domain.documents.model import Document
from signalscope.domain.documents.repository import DocumentRepository
from signalscope.domain.ingestion.adapter import IngestedItem
from signalscope.domain.ingestion.duplicates import DuplicateReason
from signalscope.domain.ingestion.writer import DocumentWriter, WriteOutcome
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

ITEM = IngestedItem(
    external_id="guid-1",
    url="https://news.example/1",
    title="  A story  ",
    content="Story text.",
    language="EN",
    published_at=datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
)


async def create_source(session_factory: async_sessionmaker[AsyncSession], name: str) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.RSS, name=name, url="https://news.example/rss")
        session.add(source)
        await session.commit()
    return source


@pytest.fixture
async def source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    return await create_source(session_factory, "Example feed")


async def load(
    session_factory: async_sessionmaker[AsyncSession], document_id: uuid.UUID
) -> Document | None:
    async with session_factory() as session:
        return await DocumentRepository(session).get(document_id)


async def test_item_becomes_a_document(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    async with session_factory() as session:
        result = await DocumentWriter(session).write(source.id, ITEM)
        await session.commit()

    assert result.outcome is WriteOutcome.CREATED
    assert result.duplicate_reason is None
    saved = await load(session_factory, result.document.id)
    assert saved is not None
    assert saved.source_id == source.id
    assert saved.external_id == "guid-1"
    assert saved.url == "https://news.example/1"
    assert saved.title == "A story"
    assert saved.content == "Story text."
    assert saved.language == "en"
    assert saved.published_at == datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    assert saved.content_hash == content_fingerprint(
        title="A story", content="Story text.", url="https://news.example/1"
    )


async def test_writer_does_not_commit(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    async with session_factory() as session:
        result = await DocumentWriter(session).write(source.id, ITEM)

    assert await load(session_factory, result.document.id) is None


async def test_duplicate_is_skipped_and_existing_document_is_kept(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    async with session_factory() as session:
        first = await DocumentWriter(session).write(source.id, ITEM)
        await session.commit()

    changed = IngestedItem(external_id="guid-1", title="A new title", content="New text.")
    async with session_factory() as session:
        second = await DocumentWriter(session).write(source.id, changed)
        await session.commit()

    assert second.outcome is WriteOutcome.DUPLICATE
    assert second.duplicate_reason is DuplicateReason.EXTERNAL_ID
    assert second.document.id == first.document.id
    saved = await load(session_factory, first.document.id)
    assert saved is not None
    assert saved.title == "A story"


async def test_repeated_content_without_identifiers_is_skipped(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    item = IngestedItem(title="Pasted note", content="Same text.")
    async with session_factory() as session:
        writer = DocumentWriter(session)
        first = await writer.write(source.id, item)
        second = await writer.write(
            source.id, IngestedItem(title="Pasted note\n", content="Same text.")
        )

    assert first.outcome is WriteOutcome.CREATED
    assert second.outcome is WriteOutcome.DUPLICATE
    assert second.duplicate_reason is DuplicateReason.CONTENT


async def test_sources_are_kept_apart(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    other_source = await create_source(session_factory, "Other feed")

    async with session_factory() as session:
        writer = DocumentWriter(session)
        first = await writer.write(source.id, ITEM)
        second = await writer.write(other_source.id, ITEM)
        await session.commit()

    assert first.outcome is WriteOutcome.CREATED
    assert second.outcome is WriteOutcome.CREATED
    assert first.document.id != second.document.id


async def test_values_too_long_for_the_database_are_dropped(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    item = IngestedItem(
        external_id="x" * 501,
        url="https://news.example/" + "y" * 2048,
        language="z" * 36,
        title="Long values",
    )
    async with session_factory() as session:
        result = await DocumentWriter(session).write(source.id, item)
        await session.commit()

    saved = await load(session_factory, result.document.id)
    assert saved is not None
    assert (saved.external_id, saved.url, saved.language) == (None, None, None)
    assert saved.title == "Long values"


async def test_blank_title_and_content_are_stored_as_none(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    item = IngestedItem(external_id="guid-blank", title="   ", content="\n\n")
    async with session_factory() as session:
        result = await DocumentWriter(session).write(source.id, item)
        await session.commit()

    saved = await load(session_factory, result.document.id)
    assert saved is not None
    assert (saved.title, saved.content, saved.content_hash) == (None, None, None)


def mixed_url(characters: int) -> str:
    # Shuffled three-byte characters, so PostgreSQL cannot shrink the index entry much.
    return "https://news.example/" + "".join(
        chr(0x4E00 + (number * 7919) % 20000) for number in range(characters)
    )


async def test_largest_allowed_url_is_stored(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    url = mixed_url(675)
    assert len(url.encode()) <= 2048

    async with session_factory() as session:
        result = await DocumentWriter(session).write(source.id, IngestedItem(url=url))
        await session.commit()

    saved = await load(session_factory, result.document.id)
    assert saved is not None
    assert saved.url == url


async def test_url_over_the_byte_limit_is_dropped(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    url = mixed_url(700)
    assert len(url) < 2048 < len(url.encode())

    async with session_factory() as session:
        result = await DocumentWriter(session).write(source.id, IngestedItem(url=url, title="Big"))
        await session.commit()

    saved = await load(session_factory, result.document.id)
    assert saved is not None
    assert saved.url is None
