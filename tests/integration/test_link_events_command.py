import io

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from event_reports import create_source, report_event
from signalscope.cli import link_events
from signalscope.core.settings import Settings

pytestmark = pytest.mark.anyio


@pytest.fixture
def settings(database_engine: AsyncEngine, migrated_database: Settings) -> Settings:
    return Settings(database_url=migrated_database.database_url)


async def run(settings: Settings, **options: int) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await link_events(settings, out, err, **options)
    return code, out.getvalue(), err.getvalue()


def counts(checked: int, linked: int, created: int) -> str:
    return f"Events checked: {checked}\nEvents linked: {linked}\nClusters created: {created}\n"


async def test_nothing_to_do(settings: Settings) -> None:
    assert await run(settings) == (0, counts(0, 0, 0), "")


async def test_one_event(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await create_source(session_factory, "Wire")
    await report_event(session_factory, source, "Harbour flood")

    assert await run(settings) == (0, counts(1, 1, 1), "")


async def test_matching_events_share_a_cluster(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    wire = await create_source(session_factory, "Wire")
    paper = await create_source(session_factory, "Paper")
    await report_event(session_factory, wire, "Harbour flood")
    await report_event(session_factory, paper, "harbour  FLOOD")
    await report_event(session_factory, paper, "Bridge closed", event_type="closure")

    assert (await run(settings))[1] == counts(3, 3, 2)


async def test_limit_and_second_run(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await create_source(session_factory, "Wire")
    for number in range(5):
        await report_event(session_factory, source, f"Flood {number}")

    assert (await run(settings, limit=3))[1] == counts(3, 3, 3)
    assert (await run(settings, limit=3))[1] == counts(2, 2, 2)
    # Everything is linked now, so another run changes nothing.
    assert (await run(settings))[1] == counts(0, 0, 0)


async def test_batches_cover_the_limit(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("signalscope.cli.LINK_EVENTS_BATCH", 2)
    source = await create_source(session_factory, "Wire")
    for number in range(5):
        await report_event(session_factory, source, f"Flood {number}")

    assert (await run(settings, limit=4))[1] == counts(4, 4, 4)
    assert (await run(settings))[1] == counts(1, 1, 1)
