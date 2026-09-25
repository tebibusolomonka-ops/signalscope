import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.domain.ingestion.model import (
    IngestionJob,
    IngestionJobStatus,
    IngestionRun,
    IngestionStatus,
)
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


async def create_run(session_factory: async_sessionmaker[AsyncSession]) -> IngestionRun:
    async with session_factory() as session:
        source = Source(type=SourceType.RSS, name="Example", url="https://example.com/rss")
        session.add(source)
        await session.flush()
        run = IngestionRun(source_id=source.id, status=IngestionStatus.PENDING)
        session.add(run)
        await session.commit()
    return run


async def add_job(
    session_factory: async_sessionmaker[AsyncSession], run: IngestionRun
) -> IngestionJob:
    async with session_factory() as session:
        job = IngestionJob(source_id=run.source_id, run_id=run.id, available_at=NOW)
        session.add(job)
        await session.commit()
    return job


async def test_new_job_defaults(session_factory: async_sessionmaker[AsyncSession]) -> None:
    run = await create_run(session_factory)

    job = await add_job(session_factory, run)

    async with session_factory() as session:
        saved = await session.get(IngestionJob, job.id)
    assert saved is not None
    assert saved.status is IngestionJobStatus.PENDING
    assert saved.available_at == NOW
    assert saved.attempt_count == 0
    assert (saved.claimed_at, saved.finished_at, saved.last_error) == (None, None, None)
    assert saved.created_at is not None


async def test_database_defaults(session_factory: async_sessionmaker[AsyncSession]) -> None:
    run = await create_run(session_factory)

    # Plain SQL skips the model defaults, so this checks the column defaults.
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "INSERT INTO ingestion_jobs (id, source_id, run_id, status, available_at) "
                    "VALUES (:id, :source_id, :run_id, 'pending', now()) "
                    "RETURNING attempt_count, created_at IS NOT NULL"
                ),
                {"id": uuid.uuid4(), "source_id": run.source_id, "run_id": run.id},
            )
        ).one()

    assert tuple(row) == (0, True)


@pytest.mark.parametrize(
    "values",
    [
        {"attempt_count": -1},
        {"status": "waiting"},
        {"available_at": None},
    ],
)
async def test_invalid_job_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, Any]
) -> None:
    run = await create_run(session_factory)
    row = {
        "id": uuid.uuid4(),
        "source_id": run.source_id,
        "run_id": run.id,
        "status": "pending",
        "available_at": NOW,
        "attempt_count": 0,
    } | values

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO ingestion_jobs "
                    "(id, source_id, run_id, status, available_at, attempt_count) "
                    "VALUES (:id, :source_id, :run_id, :status, :available_at, :attempt_count)"
                ),
                row,
            )


async def test_job_needs_an_existing_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run = await create_run(session_factory)

    async with session_factory() as session:
        session.add(IngestionJob(source_id=run.source_id, run_id=uuid.uuid4(), available_at=NOW))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_a_run_cannot_have_two_jobs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run = await create_run(session_factory)
    await add_job(session_factory, run)

    async with session_factory() as session:
        session.add(IngestionJob(source_id=run.source_id, run_id=run.id, available_at=NOW))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_run_with_a_job_cannot_be_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run = await create_run(session_factory)
    await add_job(session_factory, run)

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(delete(IngestionRun).where(IngestionRun.id == run.id))


async def test_foreign_keys_restrict_deletes(database_engine: AsyncEngine) -> None:
    async with database_engine.connect() as connection:
        foreign_keys = await connection.run_sync(
            lambda sync: inspect(sync).get_foreign_keys("ingestion_jobs")
        )

    by_column = {tuple(key["constrained_columns"]): key for key in foreign_keys}
    assert set(by_column) == {("source_id",), ("run_id",)}
    assert by_column[("source_id",)]["referred_table"] == "sources"
    assert by_column[("run_id",)]["referred_table"] == "ingestion_runs"
    assert all(key["options"]["ondelete"] == "RESTRICT" for key in foreign_keys)


async def test_indexes(database_engine: AsyncEngine) -> None:
    async with database_engine.connect() as connection:
        indexes = await connection.run_sync(
            lambda sync: inspect(sync).get_indexes("ingestion_jobs")
        )

    columns = {index["name"]: index["column_names"] for index in indexes}
    assert columns["ix_ingestion_jobs_status_available_at"] == ["status", "available_at"]
    assert columns["ix_ingestion_jobs_source_id"] == ["source_id"]
