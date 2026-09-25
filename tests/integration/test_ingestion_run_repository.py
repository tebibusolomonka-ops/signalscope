import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.ingestion.model import IngestionRun, IngestionStatus
from signalscope.domain.ingestion.repository import IngestionRunFilters, IngestionRunRepository
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

NO_FILTERS = IngestionRunFilters()


async def create_source(session_factory: async_sessionmaker[AsyncSession], name: str) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.RSS, name=name, url="https://example.com/rss")
        session.add(source)
        await session.commit()
    return source


async def add_run(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    status: IngestionStatus = IngestionStatus.PENDING,
) -> IngestionRun:
    async with session_factory() as session:
        run = await IngestionRunRepository(session).add(
            IngestionRun(source_id=source.id, status=status)
        )
        await session.commit()
    return run


@pytest.fixture
async def source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    return await create_source(session_factory, "Example feed")


async def test_add_and_get(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    run = await add_run(session_factory, source)

    async with session_factory() as session:
        saved = await IngestionRunRepository(session).get(run.id)

    assert saved is not None
    assert saved.source_id == source.id
    assert saved.status is IngestionStatus.PENDING
    assert saved.started_at is None
    assert saved.finished_at is None
    assert saved.error_message is None


async def test_get_returns_none_for_unknown_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        assert await IngestionRunRepository(session).get(uuid.uuid4()) is None


async def test_add_does_not_commit(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    async with session_factory() as session:
        run = await IngestionRunRepository(session).add(IngestionRun(source_id=source.id))

    async with session_factory() as session:
        assert await IngestionRunRepository(session).get(run.id) is None


async def test_list_page_returns_runs_in_creation_order(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    runs = [await add_run(session_factory, source) for _ in range(3)]

    async with session_factory() as session:
        listed = await IngestionRunRepository(session).list_page(NO_FILTERS, limit=10, offset=0)

    assert [run.id for run in listed] == [run.id for run in runs]


async def test_list_page_applies_limit_and_offset(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    runs = [await add_run(session_factory, source) for _ in range(5)]

    async with session_factory() as session:
        repository = IngestionRunRepository(session)
        middle = await repository.list_page(NO_FILTERS, limit=2, offset=1)
        past_the_end = await repository.list_page(NO_FILTERS, limit=2, offset=5)

    assert [run.id for run in middle] == [run.id for run in runs[1:3]]
    assert past_the_end == []


async def test_filters_and_count(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    other_source = await create_source(session_factory, "Other feed")
    await add_run(session_factory, source, IngestionStatus.COMPLETED)
    await add_run(session_factory, source, IngestionStatus.FAILED)
    await add_run(session_factory, source, IngestionStatus.COMPLETED)
    await add_run(session_factory, other_source, IngestionStatus.COMPLETED)

    cases = [
        (NO_FILTERS, 4),
        (IngestionRunFilters(source_id=source.id), 3),
        (IngestionRunFilters(status=IngestionStatus.COMPLETED), 3),
        (IngestionRunFilters(source_id=source.id, status=IngestionStatus.COMPLETED), 2),
        (IngestionRunFilters(source_id=other_source.id, status=IngestionStatus.FAILED), 0),
        (IngestionRunFilters(status=IngestionStatus.RUNNING), 0),
    ]
    async with session_factory() as session:
        repository = IngestionRunRepository(session)
        for filters, expected in cases:
            runs = await repository.list_page(filters, limit=10, offset=0)

            assert len(runs) == expected, filters
            assert await repository.count(filters) == expected, filters
            assert all(filters.source_id in (None, run.source_id) for run in runs)
            assert all(filters.status in (None, run.status) for run in runs)


async def test_counters_start_at_zero(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    run = await add_run(session_factory, source)

    async with session_factory() as session:
        saved = await IngestionRunRepository(session).get(run.id)

    assert saved is not None
    assert (saved.items_seen, saved.documents_created, saved.duplicates_skipped) == (0, 0, 0)
    assert saved.attempt_count == 0


async def test_database_sets_attempt_count_to_zero(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    # Plain SQL skips the model default, so this checks the column default.
    async with session_factory() as session:
        attempt_count = await session.scalar(
            text(
                "INSERT INTO ingestion_runs (id, source_id, status) "
                "VALUES (:id, :source_id, 'pending') RETURNING attempt_count"
            ),
            {"id": uuid.uuid4(), "source_id": source.id},
        )

    assert attempt_count == 0


@pytest.mark.parametrize(
    "counter", ["items_seen", "documents_created", "duplicates_skipped", "attempt_count"]
)
async def test_counters_cannot_be_negative(
    session_factory: async_sessionmaker[AsyncSession], source: Source, counter: str
) -> None:
    run = await add_run(session_factory, source)

    async with session_factory() as session:
        saved = await IngestionRunRepository(session).get(run.id)
        assert saved is not None
        setattr(saved, counter, -1)
        with pytest.raises(IntegrityError):
            await session.flush()
