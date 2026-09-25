import asyncio
import uuid
from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.model import Document
from signalscope.domain.ingestion.adapter import IngestedItem
from signalscope.domain.ingestion.errors import IngestionError
from signalscope.domain.ingestion.executor import IngestionExecutor
from signalscope.domain.ingestion.job_repository import IngestionJobRepository
from signalscope.domain.ingestion.model import (
    IngestionJob,
    IngestionJobStatus,
    IngestionRun,
    IngestionStatus,
)
from signalscope.domain.ingestion.registry import AdapterRegistry
from signalscope.domain.ingestion.service import IngestionRunService
from signalscope.domain.ingestion.worker import (
    UNEXPECTED_JOB_ERROR,
    IngestionWorker,
    WorkerResult,
)
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

QUEUED_AT = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)


class ListAdapter:
    def __init__(self, items: list[IngestedItem], error: Exception | None = None) -> None:
        self.items = items
        self.error = error

    async def fetch(self, source: Source) -> AsyncGenerator[IngestedItem]:
        for item in self.items:
            yield item
        if self.error is not None:
            raise self.error


def ticking_clock() -> Iterator[datetime]:
    """Each call is one minute after the one before."""
    minute = 0
    while True:
        minute += 1
        yield QUEUED_AT + timedelta(minutes=minute)


def worker(session_factory: async_sessionmaker[AsyncSession], adapter: object) -> IngestionWorker:
    registry = AdapterRegistry()
    registry.register(SourceType.RSS, adapter)  # type: ignore[arg-type]
    clock = ticking_clock()
    return IngestionWorker(
        session_factory, IngestionExecutor(session_factory, registry), clock=lambda: next(clock)
    )


async def queue_job(session_factory: async_sessionmaker[AsyncSession]) -> IngestionJob:
    async with session_factory() as session:
        source = Source(type=SourceType.RSS, name="Example", url="https://example.com/rss")
        session.add(source)
        await session.commit()
        run = await IngestionRunService(session).create(source.id)
        job = await IngestionJobRepository(session).add(
            IngestionJob(source_id=source.id, run_id=run.id, available_at=QUEUED_AT)
        )
        await session.commit()
    return job


async def reload_job(
    session_factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID
) -> IngestionJob:
    async with session_factory() as session:
        job = await IngestionJobRepository(session).get(job_id)
    assert job is not None
    return job


async def test_no_job_means_no_work(session_factory: async_sessionmaker[AsyncSession]) -> None:
    result = await worker(session_factory, ListAdapter([])).run_once()

    assert result == WorkerResult(job=None, run=None)


async def test_successful_job(session_factory: async_sessionmaker[AsyncSession]) -> None:
    queued = await queue_job(session_factory)
    adapter = ListAdapter([IngestedItem(external_id="guid-1", title="One")])

    result = await worker(session_factory, adapter).run_once()

    assert result.job is not None
    assert result.job.id == queued.id
    assert result.job.status is IngestionJobStatus.COMPLETED
    assert result.run is not None
    assert result.run.status is IngestionStatus.COMPLETED
    assert result.run.documents_created == 1
    job = await reload_job(session_factory, queued.id)
    assert job.status is IngestionJobStatus.COMPLETED
    assert job.claimed_at == QUEUED_AT + timedelta(minutes=1)
    assert job.finished_at == QUEUED_AT + timedelta(minutes=2)
    assert job.attempt_count == 1
    assert job.last_error is None
    async with session_factory() as session:
        run = await session.get(IngestionRun, queued.run_id)
        documents = (await session.scalars(select(Document))).all()
    assert run is not None
    assert run.status is IngestionStatus.COMPLETED
    assert run.attempt_count == 1
    assert len(documents) == 1


async def test_failed_ingestion_fails_the_job(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    queued = await queue_job(session_factory)
    adapter = ListAdapter([], error=IngestionError("Response is not an RSS or Atom feed."))

    result = await worker(session_factory, adapter).run_once()

    assert result.run is not None
    assert result.run.status is IngestionStatus.FAILED
    job = await reload_job(session_factory, queued.id)
    assert job.status is IngestionJobStatus.FAILED
    assert job.last_error == "Response is not an RSS or Atom feed."
    assert job.finished_at == QUEUED_AT + timedelta(minutes=2)


async def test_unexpected_failure_fails_the_job_with_a_safe_message(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    queued = await queue_job(session_factory)

    async def broken_execute(self: IngestionExecutor, run_id: uuid.UUID) -> IngestionRun:
        raise RuntimeError("password=secret")

    monkeypatch.setattr(IngestionExecutor, "execute", broken_execute)

    result = await worker(session_factory, ListAdapter([])).run_once()

    assert result.run is None
    assert result.job is not None
    job = await reload_job(session_factory, queued.id)
    assert job.status is IngestionJobStatus.FAILED
    assert job.last_error == UNEXPECTED_JOB_ERROR
    assert job.finished_at is not None


async def test_finished_job_is_not_claimed_again(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await queue_job(session_factory)
    first = worker(session_factory, ListAdapter([]))

    assert (await first.run_once()).job is not None
    assert (await first.run_once()).job is None


async def test_two_workers_do_not_run_the_same_job(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    queued = await queue_job(session_factory)

    results = await asyncio.gather(
        worker(session_factory, ListAdapter([])).run_once(),
        worker(session_factory, ListAdapter([])).run_once(),
    )

    ran = [result.job.id for result in results if result.job is not None]
    assert ran == [queued.id]
    assert (await reload_job(session_factory, queued.id)).attempt_count == 1


class CheckingAdapter:
    """Locks the job row while fetching, which fails if the worker still holds it."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID
    ) -> None:
        self.session_factory = session_factory
        self.job_id = job_id
        self.seen: list[IngestionJobStatus] = []

    async def fetch(self, source: Source) -> AsyncGenerator[IngestedItem]:
        async with self.session_factory() as session:
            # NOWAIT raises right away if any transaction still holds the row.
            job = (
                await session.scalars(
                    select(IngestionJob)
                    .where(IngestionJob.id == self.job_id)
                    .with_for_update(nowait=True)
                )
            ).one()
            self.seen.append(job.status)
        yield IngestedItem(external_id="guid-1")


async def test_claim_is_committed_before_fetching(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    queued = await queue_job(session_factory)
    adapter = CheckingAdapter(session_factory, queued.id)

    result = await worker(session_factory, adapter).run_once()

    assert adapter.seen == [IngestionJobStatus.RUNNING]
    assert result.job is not None
    assert result.job.status is IngestionJobStatus.COMPLETED
