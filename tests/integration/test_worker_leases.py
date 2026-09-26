import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.leases import LeasePolicy
from signalscope.domain.ingestion.adapter import IngestedItem
from signalscope.domain.ingestion.executor import IngestionExecutor
from signalscope.domain.ingestion.job_repository import IngestionJobRepository
from signalscope.domain.ingestion.model import (
    IngestionJob,
    IngestionJobStatus,
    IngestionRun,
    IngestionStatus,
)
from signalscope.domain.ingestion.registry import AdapterRegistry
from signalscope.domain.ingestion.worker import IngestionWorker
from signalscope.domain.processing.file_import import FileImportService, ImportedFile
from signalscope.domain.processing.job_repository import DocumentProcessingJobRepository
from signalscope.domain.processing.model import DocumentProcessingJob, ProcessingJobStatus
from signalscope.domain.processing.processor import DocumentProcessor, ProcessingResult
from signalscope.domain.processing.worker import DocumentProcessingWorker
from signalscope.domain.sources.model import Source, SourceType
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio

SessionFactory = async_sessionmaker[AsyncSession]

# Short enough to be quick, long enough that a beat cannot be missed by accident.
FAST_LEASE = LeasePolicy(timedelta(milliseconds=60))
TIMEOUT_SECONDS = 10


class Beats:
    """Records every heartbeat the worker sends."""

    def __init__(self) -> None:
        self.results: list[bool] = []
        self.beat = asyncio.Event()
        self.lost = asyncio.Event()

    def record(self, held: bool) -> None:
        self.results.append(held)
        self.beat.set()
        if not held:
            self.lost.set()

    async def wait_for(self, count: int) -> None:
        while len(self.results) < count:
            self.beat.clear()
            await asyncio.wait_for(self.beat.wait(), TIMEOUT_SECONDS)


def watch_heartbeats(monkeypatch: pytest.MonkeyPatch, worker: type, beats: Beats) -> None:
    """Record every heartbeat the worker finishes, with its result.

    The worker method returns only after its transaction has been committed,
    so a recorded beat is always visible to the test.
    """
    original = worker._heartbeat  # type: ignore[attr-defined]

    async def recording(self: object, job_id: uuid.UUID, token: uuid.UUID) -> bool:
        held = await original(self, job_id, token)
        beats.record(held)
        return held

    monkeypatch.setattr(worker, "_heartbeat", recording)


class BlockingWork:
    """Waits until the test releases it, so the lease can be watched meanwhile."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def wait(self) -> None:
        self.started.set()
        await asyncio.wait_for(self.release.wait(), TIMEOUT_SECONDS)

    async def wait_until_started(self) -> None:
        await asyncio.wait_for(self.started.wait(), TIMEOUT_SECONDS)


class BlockingAdapter:
    def __init__(self, work: BlockingWork) -> None:
        self.work = work

    async def fetch(self, source: Source) -> AsyncGenerator[IngestedItem]:
        await self.work.wait()
        yield IngestedItem(external_id="guid-1", title="Story")


class BlockingProcessor:
    def __init__(self, work: BlockingWork) -> None:
        self.work = work

    async def process(self, asset_id: uuid.UUID) -> ProcessingResult:
        await self.work.wait()
        raise AssertionError("the test releases the work only after the lease is gone")


@pytest.fixture
def blobs(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(tmp_path / "blobs")


async def create_source(
    session_factory: async_sessionmaker[AsyncSession], source_type: SourceType
) -> Source:
    async with session_factory() as session:
        source = Source(
            type=source_type,
            name="Example",
            url="https://news.example/rss" if source_type is SourceType.RSS else None,
        )
        session.add(source)
        await session.commit()
    return source


async def queue_ingestion_job(
    session_factory: async_sessionmaker[AsyncSession], source: Source
) -> IngestionJob:
    async with session_factory() as session:
        run = IngestionRun(source_id=source.id, status=IngestionStatus.PENDING)
        session.add(run)
        await session.flush()
        job = await IngestionJobRepository(session).add(
            IngestionJob(source_id=source.id, run_id=run.id, available_at=datetime.now(UTC))
        )
        await session.commit()
    return job


async def import_file(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> ImportedFile:
    async with session_factory() as session:
        return await FileImportService(session, blobs).import_file(
            source.id, filename="notes.txt", content_type="text/plain", data=b"Some notes."
        )


def ingestion_worker(
    session_factory: async_sessionmaker[AsyncSession], work: BlockingWork
) -> IngestionWorker:
    registry = AdapterRegistry()
    registry.register(SourceType.RSS, BlockingAdapter(work))
    return IngestionWorker(
        session_factory, IngestionExecutor(session_factory, registry), lease=FAST_LEASE
    )


def processing_worker(
    session_factory: async_sessionmaker[AsyncSession], work: BlockingWork
) -> DocumentProcessingWorker:
    processor = cast(DocumentProcessor, BlockingProcessor(work))
    return DocumentProcessingWorker(session_factory, processor, lease=FAST_LEASE)


async def reload_ingestion_job(
    session_factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID
) -> IngestionJob:
    async with session_factory() as session:
        job = await IngestionJobRepository(session).get(job_id)
    assert job is not None
    return job


async def reload_processing_job(
    session_factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID
) -> DocumentProcessingJob:
    async with session_factory() as session:
        job = await DocumentProcessingJobRepository(session).get(job_id)
    assert job is not None
    return job


async def test_ingestion_worker_extends_its_lease(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await create_source(session_factory, SourceType.RSS)
    job = await queue_ingestion_job(session_factory, source)
    beats = Beats()
    watch_heartbeats(monkeypatch, IngestionWorker, beats)
    work = BlockingWork()

    task = asyncio.create_task(ingestion_worker(session_factory, work).run_once())
    await work.wait_until_started()
    claimed = await reload_ingestion_job(session_factory, job.id)
    await beats.wait_for(2)
    extended = await reload_ingestion_job(session_factory, job.id)
    work.release.set()
    result = await asyncio.wait_for(task, TIMEOUT_SECONDS)

    assert all(beats.results)
    assert claimed.lease_expires_at is not None
    assert extended.lease_expires_at is not None
    assert extended.lease_expires_at > claimed.lease_expires_at
    assert extended.heartbeat_at is not None
    assert claimed.claimed_at is not None
    assert extended.heartbeat_at > claimed.claimed_at
    assert result.job is not None
    assert result.job.status is IngestionJobStatus.COMPLETED
    assert not result.lease_lost


async def test_processing_worker_extends_its_lease(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = await create_source(session_factory, SourceType.UPLOAD)
    imported = await import_file(session_factory, blobs, source)
    beats = Beats()
    watch_heartbeats(monkeypatch, DocumentProcessingWorker, beats)
    work = BlockingWork()

    task = asyncio.create_task(processing_worker(session_factory, work).run_once())
    await work.wait_until_started()
    claimed = await reload_processing_job(session_factory, imported.job.id)
    await beats.wait_for(2)
    extended = await reload_processing_job(session_factory, imported.job.id)
    work.release.set()
    await asyncio.wait_for(task, TIMEOUT_SECONDS)

    assert all(beats.results)
    assert claimed.lease_expires_at is not None
    assert extended.lease_expires_at is not None
    assert extended.lease_expires_at > claimed.lease_expires_at


async def test_heartbeat_keeps_the_job_from_being_recovered(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = await create_source(session_factory, SourceType.UPLOAD)
    await import_file(session_factory, blobs, source)
    beats = Beats()
    watch_heartbeats(monkeypatch, DocumentProcessingWorker, beats)
    work = BlockingWork()

    task = asyncio.create_task(processing_worker(session_factory, work).run_once())
    await work.wait_until_started()
    await beats.wait_for(3)
    # The lease was extended past the old end, so recovery finds nothing.
    async with session_factory() as session:
        recovered = await DocumentProcessingJobRepository(session).recover_stale(
            datetime.now(UTC), 10
        )
        await session.commit()
    work.release.set()
    await asyncio.wait_for(task, TIMEOUT_SECONDS)

    assert recovered == []


async def test_lost_lease_leaves_the_job_alone(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = await create_source(session_factory, SourceType.UPLOAD)
    imported = await import_file(session_factory, blobs, source)
    beats = Beats()
    watch_heartbeats(monkeypatch, DocumentProcessingWorker, beats)
    work = BlockingWork()

    task = asyncio.create_task(processing_worker(session_factory, work).run_once())
    await work.wait_until_started()
    # Act as if this worker stalled: its lease runs out and another one takes over.
    async with session_factory() as session:
        job = await DocumentProcessingJobRepository(session).get(imported.job.id)
        assert job is not None
        job.lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()
    async with session_factory() as session:
        [recovered] = await DocumentProcessingJobRepository(session).recover_stale(
            datetime.now(UTC), 10
        )
        await session.commit()
    await asyncio.wait_for(beats.lost.wait(), TIMEOUT_SECONDS)
    work.release.set()
    result = await asyncio.wait_for(task, TIMEOUT_SECONDS)

    assert result.lease_lost
    assert result.job is not None
    assert result.job.id == recovered.id
    # The job stays as the other worker left it, waiting to be claimed again.
    saved = await reload_processing_job(session_factory, imported.job.id)
    assert saved.status is ProcessingJobStatus.PENDING
    assert saved.finished_at is None
    assert saved.last_error is None


async def test_ingestion_lost_lease_leaves_the_job_alone(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await create_source(session_factory, SourceType.RSS)
    job = await queue_ingestion_job(session_factory, source)
    beats = Beats()
    watch_heartbeats(monkeypatch, IngestionWorker, beats)
    work = BlockingWork()

    task = asyncio.create_task(ingestion_worker(session_factory, work).run_once())
    await work.wait_until_started()
    async with session_factory() as session:
        claimed = await IngestionJobRepository(session).get(job.id)
        assert claimed is not None
        claimed.lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()
    async with session_factory() as session:
        await IngestionJobRepository(session).recover_stale(datetime.now(UTC), 10)
        await session.commit()
    await asyncio.wait_for(beats.lost.wait(), TIMEOUT_SECONDS)
    work.release.set()
    result = await asyncio.wait_for(task, TIMEOUT_SECONDS)

    assert result.lease_lost
    saved = await reload_ingestion_job(session_factory, job.id)
    assert saved.status is IngestionJobStatus.PENDING
    assert saved.finished_at is None


async def take_over(
    repository_type: type, session_factory: SessionFactory, job_id: uuid.UUID
) -> Any:
    """Act as if the worker stalled: recover its job and let another worker claim it."""
    later = datetime.now(UTC) + timedelta(hours=1)
    async with session_factory() as session:
        [recovered] = await repository_type(session).recover_stale(later, 10)
        await session.commit()
    assert recovered.id == job_id
    async with session_factory() as session:
        claimed = await repository_type(session).claim_next(later)
        await session.commit()
    assert claimed is not None and claimed.id == job_id
    return claimed


async def test_ingestion_worker_cannot_finish_a_job_claimed_again(
    session_factory: SessionFactory,
) -> None:
    source = await create_source(session_factory, SourceType.RSS)
    job = await queue_ingestion_job(session_factory, source)
    work = BlockingWork()
    registry = AdapterRegistry()
    registry.register(SourceType.RSS, BlockingAdapter(work))
    # The default lease is long, so no heartbeat notices the takeover first.
    worker = IngestionWorker(session_factory, IngestionExecutor(session_factory, registry))

    task = asyncio.create_task(worker.run_once())
    await work.wait_until_started()
    other = await take_over(IngestionJobRepository, session_factory, job.id)
    work.release.set()
    result = await asyncio.wait_for(task, TIMEOUT_SECONDS)

    assert result.lease_lost
    saved = await reload_ingestion_job(session_factory, job.id)
    assert saved.status is IngestionJobStatus.RUNNING
    assert saved.lease_token == other.lease_token
    assert saved.finished_at is None


async def test_processing_worker_cannot_finish_a_job_claimed_again(
    session_factory: SessionFactory, blobs: LocalBlobStore
) -> None:
    source = await create_source(session_factory, SourceType.UPLOAD)
    imported = await import_file(session_factory, blobs, source)
    work = BlockingWork()
    # The default lease is long, so no heartbeat notices the takeover first.
    worker = DocumentProcessingWorker(
        session_factory, cast(DocumentProcessor, BlockingProcessor(work))
    )

    task = asyncio.create_task(worker.run_once())
    await work.wait_until_started()
    other = await take_over(DocumentProcessingJobRepository, session_factory, imported.job.id)
    work.release.set()
    result = await asyncio.wait_for(task, TIMEOUT_SECONDS)

    # The work failed, but the failure belongs to a worker that no longer holds the job.
    assert result.lease_lost
    saved = await reload_processing_job(session_factory, imported.job.id)
    assert saved.status is ProcessingJobStatus.RUNNING
    assert saved.lease_token == other.lease_token
    assert saved.last_error is None
