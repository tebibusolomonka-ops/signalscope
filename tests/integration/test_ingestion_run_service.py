import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import NotFoundError
from signalscope.domain.ingestion.model import IngestionRun, IngestionStatus
from signalscope.domain.ingestion.repository import IngestionRunFilters
from signalscope.domain.ingestion.service import IngestionRunService, InvalidStatusChangeError
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio


@pytest.fixture
async def source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.RSS, name="Example feed", url="https://example.com/rss")
        session.add(source)
        await session.commit()
    return source


async def create_run(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> IngestionRun:
    async with session_factory() as session:
        return await IngestionRunService(session).create(source.id)


async def run_with_status(
    session_factory: async_sessionmaker[AsyncSession], source: Source, status: IngestionStatus
) -> uuid.UUID:
    """Create a run and move it to the given status through allowed changes."""
    run = await create_run(session_factory, source)
    async with session_factory() as session:
        service = IngestionRunService(session)
        if status is not IngestionStatus.PENDING:
            await service.mark_running(run.id)
        if status is IngestionStatus.COMPLETED:
            await service.mark_completed(run.id)
        if status is IngestionStatus.FAILED:
            await service.mark_failed(run.id, "Feed was not reachable.")
    return run.id


async def load(
    session_factory: async_sessionmaker[AsyncSession], run_id: uuid.UUID
) -> IngestionRun:
    async with session_factory() as session:
        return await IngestionRunService(session).get(run_id)


async def test_create_makes_pending_run(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    run = await create_run(session_factory, source)

    saved = await load(session_factory, run.id)
    assert saved.source_id == source.id
    assert saved.status is IngestionStatus.PENDING
    assert (saved.started_at, saved.finished_at, saved.error_message) == (None, None, None)


async def test_create_for_unknown_source_raises_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError, match="Source was not found."):
            await IngestionRunService(session).create(uuid.uuid4())


async def test_get_unknown_run_raises_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError, match="Ingestion run was not found."):
            await IngestionRunService(session).get(uuid.uuid4())


async def test_list_page_filters_by_status(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    pending = await run_with_status(session_factory, source, IngestionStatus.PENDING)
    await run_with_status(session_factory, source, IngestionStatus.COMPLETED)

    async with session_factory() as session:
        runs, total = await IngestionRunService(session).list_page(
            IngestionRunFilters(status=IngestionStatus.PENDING), limit=10, offset=0
        )

    assert [run.id for run in runs] == [pending]
    assert total == 1


async def test_mark_running_sets_started_at(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    run = await create_run(session_factory, source)
    before = datetime.now(UTC)

    async with session_factory() as session:
        await IngestionRunService(session).mark_running(run.id)

    saved = await load(session_factory, run.id)
    assert saved.status is IngestionStatus.RUNNING
    assert saved.started_at is not None
    assert saved.started_at >= before
    assert saved.started_at.utcoffset() is not None
    assert saved.finished_at is None


async def test_mark_completed_sets_finished_at(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    run_id = await run_with_status(session_factory, source, IngestionStatus.COMPLETED)

    saved = await load(session_factory, run_id)
    assert saved.status is IngestionStatus.COMPLETED
    assert saved.started_at is not None
    assert saved.finished_at is not None
    assert saved.finished_at >= saved.started_at
    assert saved.error_message is None


async def test_mark_failed_stores_error_message(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    run_id = await run_with_status(session_factory, source, IngestionStatus.FAILED)

    saved = await load(session_factory, run_id)
    assert saved.status is IngestionStatus.FAILED
    assert saved.finished_at is not None
    assert saved.error_message == "Feed was not reachable."


async def test_long_error_message_is_cut(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> None:
    run_id = await run_with_status(session_factory, source, IngestionStatus.RUNNING)

    async with session_factory() as session:
        await IngestionRunService(session).mark_failed(run_id, "  " + "x" * 5000 + "  ")

    saved = await load(session_factory, run_id)
    assert saved.error_message is not None
    assert len(saved.error_message) == 1000
    assert saved.error_message.endswith("...")


@pytest.mark.parametrize(
    ("current", "change"),
    [
        (IngestionStatus.PENDING, "mark_completed"),
        (IngestionStatus.PENDING, "mark_failed"),
        (IngestionStatus.RUNNING, "mark_running"),
        (IngestionStatus.COMPLETED, "mark_running"),
        (IngestionStatus.COMPLETED, "mark_failed"),
        (IngestionStatus.FAILED, "mark_running"),
        (IngestionStatus.FAILED, "mark_completed"),
    ],
)
async def test_invalid_status_changes_are_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    current: IngestionStatus,
    change: str,
) -> None:
    run_id = await run_with_status(session_factory, source, current)

    async with session_factory() as session:
        service = IngestionRunService(session)
        method = getattr(service, change)
        arguments = [run_id, "Should not be stored."] if change == "mark_failed" else [run_id]
        with pytest.raises(InvalidStatusChangeError, match=f"Ingestion run is {current}"):
            await method(*arguments)

        # The rollback leaves the session usable.
        assert (await service.get(run_id)).status is current

    assert (await load(session_factory, run_id)).status is current


async def test_changing_unknown_run_raises_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError, match="Ingestion run was not found."):
            await IngestionRunService(session).mark_running(uuid.uuid4())
