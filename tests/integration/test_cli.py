import io
import re
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.cli import ingest_source, run_worker, schedule_ingestion
from signalscope.core.settings import Settings
from signalscope.domain.ingestion.adapter import IngestedItem
from signalscope.domain.ingestion.errors import IngestionError
from signalscope.domain.ingestion.registry import AdapterRegistry
from signalscope.domain.ingestion.repository import IngestionRunFilters, IngestionRunRepository
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio


class ListAdapter:
    def __init__(self, items: list[IngestedItem], error: Exception | None = None) -> None:
        self.items = items
        self.error = error

    async def fetch(self, source: Source) -> AsyncGenerator[IngestedItem]:
        for item in self.items:
            yield item
        if self.error is not None:
            raise self.error


def rss_registry(adapter: ListAdapter) -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(SourceType.RSS, adapter)
    return registry


@pytest.fixture
def settings(database_engine: AsyncEngine, migrated_database: Settings) -> Settings:
    return migrated_database


async def create_source(
    session_factory: async_sessionmaker[AsyncSession], source_type: SourceType
) -> Source:
    async with session_factory() as session:
        source = Source(type=source_type, name="Example", url="https://news.example/rss")
        session.add(source)
        await session.commit()
    return source


async def run_cli(
    settings: Settings, source_id: uuid.UUID, registry: AdapterRegistry
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await ingest_source(source_id, settings, registry, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


async def test_unknown_source(settings: Settings) -> None:
    code, out, err = await run_cli(settings, uuid.uuid4(), rss_registry(ListAdapter([])))

    assert code == 1
    assert out == ""
    assert err == "Error: Source was not found.\n"


async def test_unsupported_source_type_creates_no_run(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await create_source(session_factory, SourceType.UPLOAD)

    code, _, err = await run_cli(settings, source.id, rss_registry(ListAdapter([])))

    assert code == 1
    assert err == "Error: No ingestion adapter is available for upload sources.\n"
    async with session_factory() as session:
        assert await IngestionRunRepository(session).count(IngestionRunFilters()) == 0


async def test_successful_run_prints_the_result(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await create_source(session_factory, SourceType.RSS)
    items = [
        IngestedItem(external_id="guid-1", title="One"),
        IngestedItem(external_id="guid-2", title="Two"),
        IngestedItem(external_id="guid-1", title="One again"),
    ]

    code, out, err = await run_cli(settings, source.id, rss_registry(ListAdapter(items)))

    assert code == 0
    assert err == ""
    assert re.fullmatch(
        r"Run: [0-9a-f-]{36}\nStatus: completed\nItems: 3\nCreated: 2\nDuplicates: 1\n", out
    )


async def test_failed_run_exits_with_an_error(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source = await create_source(session_factory, SourceType.RSS)
    adapter = ListAdapter(
        [IngestedItem(external_id="guid-1")], error=IngestionError("Feed went away.")
    )

    code, out, _ = await run_cli(settings, source.id, rss_registry(adapter))

    assert code == 1
    assert out.splitlines()[1:] == [
        "Status: failed",
        "Items: 1",
        "Created: 1",
        "Duplicates: 0",
        "Error: Feed went away.",
    ]


async def create_due_source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    async with session_factory() as session:
        source = Source(
            type=SourceType.RSS,
            name="Example",
            url="https://news.example/rss",
            ingestion_enabled=True,
            ingestion_interval_minutes=60,
            next_ingestion_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        session.add(source)
        await session.commit()
    return source


async def run_schedule_cli(settings: Settings) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await schedule_ingestion(10, settings, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


async def run_worker_cli(settings: Settings, registry: AdapterRegistry) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await run_worker(settings, registry, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


async def test_schedule_without_due_sources(settings: Settings) -> None:
    assert await run_schedule_cli(settings) == (0, "Sources due: 0\nJobs created: 0\n", "")


async def test_schedule_prints_the_jobs_created(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await create_due_source(session_factory)
    await create_due_source(session_factory)

    assert await run_schedule_cli(settings) == (0, "Sources due: 2\nJobs created: 2\n", "")
    assert await run_schedule_cli(settings) == (0, "Sources due: 0\nJobs created: 0\n", "")


async def test_worker_without_jobs(settings: Settings) -> None:
    result = await run_worker_cli(settings, rss_registry(ListAdapter([])))

    assert result == (0, "No ingestion job available.\n", "")


async def test_worker_runs_a_queued_job(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await create_due_source(session_factory)
    await run_schedule_cli(settings)
    adapter = ListAdapter([IngestedItem(external_id="guid-1", title="One")])

    code, out, err = await run_worker_cli(settings, rss_registry(adapter))

    assert code == 0
    assert err == ""
    assert re.fullmatch(r"Job: [0-9a-f-]{36}\nStatus: completed\n", out)
    assert (await run_worker_cli(settings, rss_registry(adapter)))[1] == (
        "No ingestion job available.\n"
    )


async def test_worker_reports_a_failed_job(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await create_due_source(session_factory)
    await run_schedule_cli(settings)
    adapter = ListAdapter([], error=IngestionError("Feed went away."))

    code, out, _ = await run_worker_cli(settings, rss_registry(adapter))

    assert code == 1
    assert out.splitlines()[1:] == ["Status: failed", "Error: Feed went away."]
