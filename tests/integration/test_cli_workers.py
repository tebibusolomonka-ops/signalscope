import io
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.cli import import_file, run_processing_worker, run_worker, schedule_ingestion
from signalscope.core.settings import Settings
from signalscope.domain.ingestion.adapter import IngestedItem
from signalscope.domain.ingestion.registry import AdapterRegistry
from signalscope.domain.processing.job_repository import DocumentProcessingJobRepository
from signalscope.domain.processing.model import DocumentProcessingJob, ProcessingJobStatus
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio


class OneItemAdapter:
    async def fetch(self, source: Source) -> AsyncGenerator[IngestedItem]:
        yield IngestedItem(external_id=f"guid-{source.id}", title="Story")


@pytest.fixture
def settings(database_engine: AsyncEngine, migrated_database: Settings, tmp_path: Path) -> Settings:
    return Settings(database_url=migrated_database.database_url, blob_dir=tmp_path / "blobs")


async def create_source(
    session_factory: async_sessionmaker[AsyncSession], source_type: SourceType
) -> Source:
    async with session_factory() as session:
        due = source_type is SourceType.RSS
        source = Source(
            type=source_type,
            name="Example",
            url="https://news.example/rss" if due else None,
            ingestion_enabled=due,
            ingestion_interval_minutes=60 if due else None,
            next_ingestion_at=datetime.now(UTC) - timedelta(minutes=5) if due else None,
        )
        session.add(source)
        await session.commit()
    return source


async def import_text(settings: Settings, source: Source, tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(f"Text of {name}.".encode())
    code = await import_file(source.id, path, settings, out=io.StringIO(), err=io.StringIO())
    assert code == 0


async def test_processing_worker_loop_stops_after_max_jobs(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    source = await create_source(session_factory, SourceType.UPLOAD)
    for name in ["one.txt", "two.txt", "three.txt"]:
        await import_text(settings, source, tmp_path, name)
    out = io.StringIO()

    code = await run_processing_worker(
        settings, out, io.StringIO(), once=False, poll_seconds=0.01, max_jobs=2
    )

    assert code == 0
    lines = out.getvalue().splitlines()
    assert lines.count("Status: completed") == 2
    assert lines[-1] == "Jobs handled: 2"


async def test_ingestion_worker_loop_stops_after_max_jobs(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    for _ in range(2):
        await create_source(session_factory, SourceType.RSS)
    await schedule_ingestion(10, settings, out=io.StringIO(), err=io.StringIO())
    registry = AdapterRegistry()
    registry.register(SourceType.RSS, OneItemAdapter())
    out = io.StringIO()

    code = await run_worker(
        settings, registry, out, io.StringIO(), once=False, poll_seconds=0.01, max_jobs=2
    )

    assert code == 0
    lines = out.getvalue().splitlines()
    assert lines.count("Status: completed") == 2
    assert lines[-1] == "Jobs handled: 2"


async def test_worker_recovers_a_stale_job_before_claiming(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    source = await create_source(session_factory, SourceType.UPLOAD)
    await import_text(settings, source, tmp_path, "notes.txt")
    # Act as if a worker claimed the job and then crashed, so its lease ran out.
    async with session_factory() as session:
        job = await DocumentProcessingJobRepository(session).claim_next(datetime.now(UTC))
        assert job is not None
        job.lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()
    assert job is not None

    out = io.StringIO()
    code = await run_processing_worker(settings, out, io.StringIO())

    assert code == 0
    assert f"Job: {job.id}" in out.getvalue()
    async with session_factory() as session:
        saved = await session.get(DocumentProcessingJob, job.id)
    assert saved is not None
    assert saved.status is ProcessingJobStatus.COMPLETED
    assert saved.attempt_count == 2
