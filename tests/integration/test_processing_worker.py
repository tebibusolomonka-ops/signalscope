import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sample_files import make_docx, make_pdf
from signalscope.domain.documents.model import Document
from signalscope.domain.processing.file_import import FileImportService, ImportedFile
from signalscope.domain.processing.job_repository import DocumentProcessingJobRepository
from signalscope.domain.processing.model import DocumentProcessingJob, ProcessingJobStatus
from signalscope.domain.processing.processor import DocumentProcessor, ProcessingResult
from signalscope.domain.processing.worker import (
    UNEXPECTED_PROCESSING_ERROR,
    DocumentProcessingWorker,
    ProcessingWorkerResult,
)
from signalscope.domain.sources.model import Source, SourceType
from signalscope.parsing.docx_document import DOCX_CONTENT_TYPE
from signalscope.parsing.registry import create_default_parser_registry
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio

QUEUED_AT = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)


@pytest.fixture
def blobs(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(tmp_path / "blobs")


@pytest.fixture
async def source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.commit()
    return source


def ticking_clock() -> Iterator[datetime]:
    """Each call is one minute after the one before."""
    minute = 0
    while True:
        minute += 1
        yield QUEUED_AT + timedelta(minutes=minute)


def worker(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> DocumentProcessingWorker:
    clock = ticking_clock()
    processor = DocumentProcessor(session_factory, blobs, create_default_parser_registry())
    return DocumentProcessingWorker(session_factory, processor, clock=lambda: next(clock))


async def import_file(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    source: Source,
    data: bytes,
    content_type: str,
    filename: str = "upload",
) -> ImportedFile:
    async with session_factory() as session:
        return await FileImportService(session, blobs, clock=lambda: QUEUED_AT).import_file(
            source.id, filename=filename, content_type=content_type, data=data
        )


async def reload(
    session_factory: async_sessionmaker[AsyncSession], imported: ImportedFile
) -> tuple[DocumentProcessingJob, Document]:
    async with session_factory() as session:
        job = await session.get(DocumentProcessingJob, imported.job.id)
        document = await session.get(Document, imported.document.id)
    assert job is not None
    assert document is not None
    return job, document


async def test_no_job_means_no_work(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    assert await worker(session_factory, blobs).run_once() == ProcessingWorkerResult(job=None)


@pytest.mark.parametrize(
    ("data", "content_type", "content"),
    [
        (b"Climate policy notes.", "text/plain", "Climate policy notes."),
        (make_pdf(["Page one", "Page two"]), "application/pdf", "Page one\n\nPage two"),
        (make_docx(["Hello", "World"]), DOCX_CONTENT_TYPE, "Hello\n\nWorld"),
    ],
    ids=["txt", "pdf", "docx"],
)
async def test_successful_job(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    source: Source,
    data: bytes,
    content_type: str,
    content: str,
) -> None:
    imported = await import_file(session_factory, blobs, source, data, content_type)

    result = await worker(session_factory, blobs).run_once()

    assert result.job is not None
    assert result.job.id == imported.job.id
    assert result.job.status is ProcessingJobStatus.COMPLETED
    job, document = await reload(session_factory, imported)
    assert job.status is ProcessingJobStatus.COMPLETED
    assert job.claimed_at == QUEUED_AT + timedelta(minutes=1)
    assert job.finished_at == QUEUED_AT + timedelta(minutes=2)
    assert job.attempt_count == 1
    assert job.last_error is None
    assert document.content == content


@pytest.mark.parametrize(
    ("data", "content_type", "error"),
    [
        (b"\x89PNG data", "image/png", "No parser is available for image/png."),
        (b"{not json", "application/json", "Document is not valid JSON."),
        (b"%PDF-1.4 broken", "application/pdf", "Document is not a readable PDF."),
    ],
    ids=["unsupported", "bad-json", "bad-pdf"],
)
async def test_failed_processing_fails_the_job(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    source: Source,
    data: bytes,
    content_type: str,
    error: str,
) -> None:
    imported = await import_file(session_factory, blobs, source, data, content_type)

    result = await worker(session_factory, blobs).run_once()

    assert result.job is not None
    assert result.job.status is ProcessingJobStatus.FAILED
    job, document = await reload(session_factory, imported)
    assert job.status is ProcessingJobStatus.FAILED
    assert job.last_error == error
    assert job.finished_at == QUEUED_AT + timedelta(minutes=2)
    assert job.attempt_count == 1
    assert document.content is None


async def test_missing_blob_fails_the_job(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    imported = await import_file(session_factory, blobs, source, b"hello", "text/plain")
    await blobs.delete(imported.asset.storage_key)

    await worker(session_factory, blobs).run_once()

    job, _ = await reload(session_factory, imported)
    assert job.status is ProcessingJobStatus.FAILED
    assert job.last_error == "Stored file was not found."


async def test_unexpected_failure_is_stored_as_a_safe_message(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    source: Source,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported = await import_file(session_factory, blobs, source, b"hello", "text/plain")

    async def broken_process(self: DocumentProcessor, asset_id: uuid.UUID) -> ProcessingResult:
        raise RuntimeError("password=secret")

    monkeypatch.setattr(DocumentProcessor, "process", broken_process)

    await worker(session_factory, blobs).run_once()

    job, _ = await reload(session_factory, imported)
    assert job.status is ProcessingJobStatus.FAILED
    assert job.last_error == UNEXPECTED_PROCESSING_ERROR


async def test_finished_job_is_not_claimed_again(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    await import_file(session_factory, blobs, source, b"hello", "text/plain")
    one_worker = worker(session_factory, blobs)

    assert (await one_worker.run_once()).job is not None
    assert (await one_worker.run_once()).job is None


async def test_two_workers_do_not_run_the_same_job(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    imported = await import_file(session_factory, blobs, source, b"hello", "text/plain")

    results = await asyncio.gather(
        worker(session_factory, blobs).run_once(), worker(session_factory, blobs).run_once()
    )

    assert [result.job.id for result in results if result.job is not None] == [imported.job.id]
    job, _ = await reload(session_factory, imported)
    assert job.attempt_count == 1


class CheckingBlobStore(LocalBlobStore):
    """Locks the job row while the file is read, which fails if the worker still holds it."""

    def __init__(
        self, root: Path, session_factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID
    ) -> None:
        super().__init__(root)
        self.session_factory = session_factory
        self.job_id = job_id
        self.seen: list[ProcessingJobStatus] = []

    async def get(self, key: str) -> bytes:
        async with self.session_factory() as session:
            # NOWAIT raises right away if any transaction still holds the row.
            job = (
                await session.scalars(
                    select(DocumentProcessingJob)
                    .where(DocumentProcessingJob.id == self.job_id)
                    .with_for_update(nowait=True)
                )
            ).one()
            self.seen.append(job.status)
        return await super().get(key)


async def test_claim_is_committed_before_the_file_is_read(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    source: Source,
) -> None:
    imported = await import_file(session_factory, blobs, source, b"hello", "text/plain")
    checking = CheckingBlobStore(blobs.root, session_factory, imported.job.id)

    result = await worker(session_factory, checking).run_once()

    assert checking.seen == [ProcessingJobStatus.RUNNING]
    assert result.job is not None
    assert result.job.status is ProcessingJobStatus.COMPLETED


async def test_job_that_is_not_available_yet_waits(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, source: Source
) -> None:
    imported = await import_file(session_factory, blobs, source, b"hello", "text/plain")
    async with session_factory() as session:
        job = await DocumentProcessingJobRepository(session).get(imported.job.id)
        assert job is not None
        job.available_at = QUEUED_AT + timedelta(days=1)
        await session.commit()

    assert (await worker(session_factory, blobs).run_once()).job is None
