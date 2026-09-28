import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from event_reports import create_source
from signalscope.core.errors import InvalidInputError, NotFoundError
from signalscope.dashboard.sources import SourceActivityDay, SourceActivityService
from signalscope.domain.documents.model import Document

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def at(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 3, day, hour, 0, tzinfo=UTC)


async def add_document(
    session_factory: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    created_at: datetime,
    published_at: datetime | None = None,
) -> None:
    async with session_factory() as session:
        session.add(Document(source_id=source_id, created_at=created_at, published_at=published_at))
        await session.commit()


async def daily(
    session_factory: async_sessionmaker[AsyncSession],
    days: int,
    source_id: uuid.UUID | None = None,
) -> list[SourceActivityDay]:
    async with session_factory() as session:
        return await SourceActivityService(session, clock=lambda: NOW).daily(days, source_id)


async def test_empty(session_factory: async_sessionmaker[AsyncSession]) -> None:
    found = await daily(session_factory, 30)

    assert len(found) == 30
    assert found[0].date == date(2026, 2, 9)
    assert found[-1].date == date(2026, 3, 10)
    assert all((day.documents_created, day.documents_published) == (0, 0) for day in found)


async def test_created_and_published_with_zero_gaps(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source = await create_source(session_factory, "Wire")
    await add_document(session_factory, source, at(8), published_at=at(1))
    await add_document(session_factory, source, at(8, 23), published_at=at(10))
    await add_document(session_factory, source, at(10))
    # Outside the five days asked for.
    await add_document(session_factory, source, at(2), published_at=at(2))

    found = await daily(session_factory, 5)

    assert [(day.date.day, day.documents_created, day.documents_published) for day in found] == [
        (6, 0, 0),
        (7, 0, 0),
        (8, 2, 0),
        (9, 0, 0),
        (10, 1, 1),
    ]


async def test_days_are_utc(session_factory: async_sessionmaker[AsyncSession]) -> None:
    source = await create_source(session_factory, "Wire")
    # 23:30 on 9 March in UTC-2 is 01:30 on 10 March in UTC.
    await add_document(session_factory, source, at(10, 1) + timedelta(minutes=30))

    found = await daily(session_factory, 2)

    assert [day.documents_created for day in found] == [0, 1]


async def test_source_filter(session_factory: async_sessionmaker[AsyncSession]) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    await add_document(session_factory, wire, at(10))
    await add_document(session_factory, paper, at(10))
    await add_document(session_factory, paper, at(9))

    everything = await daily(session_factory, 2)
    only_paper = await daily(session_factory, 2, paper)

    assert [day.documents_created for day in everything] == [1, 2]
    assert [day.documents_created for day in only_paper] == [1, 1]


async def test_bounds_and_unknown_source(session_factory: async_sessionmaker[AsyncSession]) -> None:
    with pytest.raises(InvalidInputError):
        await daily(session_factory, 0)
    with pytest.raises(InvalidInputError):
        await daily(session_factory, 366)
    with pytest.raises(NotFoundError):
        await daily(session_factory, 7, uuid.uuid4())
    assert len(await daily(session_factory, 365)) == 365
