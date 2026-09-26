import argparse
import asyncio
import mimetypes
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TextIO

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import SignalScopeError
from signalscope.core.logging import configure_logging
from signalscope.core.settings import Settings, SettingsError, load_settings
from signalscope.db.engine import create_database_engine
from signalscope.db.session import create_session_factory
from signalscope.domain.blobs.cleanup import BlobCleanupService
from signalscope.domain.documents.files import MAX_FILE_BYTES
from signalscope.domain.ingestion.executor import IngestionExecutor
from signalscope.domain.ingestion.model import (
    IngestionJob,
    IngestionJobStatus,
    IngestionRun,
    IngestionStatus,
)
from signalscope.domain.ingestion.recovery import recover_stale_ingestion_jobs
from signalscope.domain.ingestion.registry import AdapterRegistry, UnsupportedSourceTypeError
from signalscope.domain.ingestion.scheduler import IngestionScheduler
from signalscope.domain.ingestion.service import IngestionRunService
from signalscope.domain.ingestion.worker import IngestionWorker
from signalscope.domain.processing.file_import import FileImportService
from signalscope.domain.processing.job_repository import DocumentProcessingJobRepository
from signalscope.domain.processing.model import DocumentProcessingJob, ProcessingJobStatus
from signalscope.domain.processing.processor import DocumentProcessor
from signalscope.domain.processing.worker import DocumentProcessingWorker
from signalscope.domain.sources.model import SourceType
from signalscope.domain.sources.repository import SourceRepository
from signalscope.domain.sources.scheduling import utc_now
from signalscope.embeddings.runtime import local_embedding_target
from signalscope.ingestion.http import HttpFetcher
from signalscope.ingestion.rss import RssIngestionAdapter
from signalscope.ingestion.web import WebIngestionAdapter
from signalscope.parsing.docx_document import DOCX_CONTENT_TYPE
from signalscope.parsing.registry import create_default_parser_registry
from signalscope.storage.local import LocalBlobStore
from signalscope.workers.runner import DEFAULT_POLL_SECONDS, WorkerLoop
from signalscope.workers.shutdown import stop_on_signals

DEFAULT_SCHEDULE_LIMIT = 100
DEFAULT_CLEANUP_LIMIT = 100
NO_DATABASE_ERROR = "Error: Database URL is not configured. Set SIGNALSCOPE_DATABASE_URL."
NO_BLOB_DIR_ERROR = "Error: Blob directory is not configured. Set SIGNALSCOPE_BLOB_DIR."
# Stale jobs put back in the queue before each claim.
RECOVERY_LIMIT = 10
LEASE_LOST_MESSAGE = "Lease lost: another worker took the job over."
STOPPING_MESSAGE = "Stopping after the current job."

# Only the types built into Python, so the guess does not depend on the machine.
MIME_TYPES = mimetypes.MimeTypes()
MIME_TYPES.add_type(DOCX_CONTENT_TYPE, ".docx")
MIME_TYPES.add_type("application/xhtml+xml", ".xhtml")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _check_worker_options(parser, args)

    try:
        settings = load_settings()
    except SettingsError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    configure_logging(settings)
    if args.command == "ingest-source":
        return asyncio.run(ingest_source(args.source_id, settings))
    if args.command == "schedule-ingestion":
        return asyncio.run(schedule_ingestion(args.limit, settings))
    if args.command == "import-file":
        return asyncio.run(import_file(args.source_id, args.path, settings, args.content_type))
    if args.command == "cleanup-blobs":
        return asyncio.run(cleanup_blobs(args.limit, settings))
    loop_options = {
        "once": args.once,
        "poll_seconds": args.poll_seconds,
        "max_jobs": args.max_jobs,
    }
    try:
        if args.command == "run-worker":
            return asyncio.run(run_worker(settings, **loop_options))
        return asyncio.run(run_processing_worker(settings, **loop_options))
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="signalscope", description="SignalScope tools.")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest-source", help="fetch new content for one source")
    ingest.add_argument("source_id", type=uuid.UUID, help="ID of the source")

    schedule = commands.add_parser(
        "schedule-ingestion", help="queue ingestion jobs for sources that are due"
    )
    schedule.add_argument(
        "--limit",
        type=positive_int,
        default=DEFAULT_SCHEDULE_LIMIT,
        help=f"most sources to queue (default: {DEFAULT_SCHEDULE_LIMIT})",
    )

    import_command = commands.add_parser(
        "import-file", help="store a local file and queue it for processing"
    )
    import_command.add_argument("source_id", type=uuid.UUID, help="ID of an upload source")
    import_command.add_argument("path", type=Path, help="the file to import")
    import_command.add_argument(
        "--content-type", help="media type of the file (default: guessed from the file name)"
    )

    cleanup = commands.add_parser("cleanup-blobs", help="delete stored files that were left behind")
    cleanup.add_argument(
        "--limit",
        type=positive_int,
        default=DEFAULT_CLEANUP_LIMIT,
        help=f"most files to try (default: {DEFAULT_CLEANUP_LIMIT})",
    )

    worker = commands.add_parser("run-worker", help="run queued ingestion jobs")
    _add_worker_options(worker)

    processing = commands.add_parser("run-processing-worker", help="parse queued imported files")
    _add_worker_options(processing)
    return parser


def _add_worker_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--once",
        action="store_true",
        help="run at most one job, then exit (default: keep running until stopped)",
    )
    parser.add_argument(
        "--poll-seconds",
        type=positive_float,
        default=None,
        help=f"seconds to wait when there is no work (default: {DEFAULT_POLL_SECONDS:g})",
    )
    parser.add_argument(
        "--max-jobs", type=positive_int, default=None, help="exit after this many jobs"
    )


def _check_worker_options(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    is_worker = args.command in ("run-worker", "run-processing-worker")
    loop_option_given = is_worker and (args.poll_seconds is not None or args.max_jobs is not None)
    if loop_option_given and args.once:
        parser.error("--once cannot be used with --poll-seconds or --max-jobs")


def positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a number: {value!r}") from None
    if not number > 0 or number == float("inf"):
        raise argparse.ArgumentTypeError(f"must be a positive number: {value}")
    return number


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a whole number: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1: {number}")
    return number


def build_registry(fetcher: HttpFetcher) -> AdapterRegistry:
    """Adapters for the source types SignalScope can fetch on its own."""
    registry = AdapterRegistry()
    registry.register(SourceType.RSS, RssIngestionAdapter(fetcher))
    registry.register(SourceType.WEB, WebIngestionAdapter(fetcher))
    return registry


async def ingest_source(
    source_id: uuid.UUID,
    settings: Settings,
    registry: AdapterRegistry | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run ingestion for one source and print the result. Returns the exit code."""
    # Looked up at call time, so a replaced sys.stdout or sys.stderr is used.
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    async with _database(settings) as session_factory, _adapters(registry) as adapters:
        return await _ingest(source_id, session_factory, adapters, out, err)


async def schedule_ingestion(
    limit: int, settings: Settings, out: TextIO | None = None, err: TextIO | None = None
) -> int:
    """Queue jobs for due sources and print how many. Returns the exit code."""
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    async with _database(settings) as session_factory:
        result = await IngestionScheduler(session_factory).schedule_due(limit)
    print(f"Sources due: {result.sources_considered}", file=out)
    print(f"Jobs created: {result.jobs_created}", file=out)
    return 0


async def cleanup_blobs(
    limit: int, settings: Settings, out: TextIO | None = None, err: TextIO | None = None
) -> int:
    """Delete files that were left behind and print the counts. Returns the exit code.

    The exit code is 1 when a file could not be deleted. It is tried again later.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1
    if settings.blob_dir is None:
        print(NO_BLOB_DIR_ERROR, file=err)
        return 1

    blobs = LocalBlobStore(settings.blob_dir)
    async with _database(settings) as session_factory:
        result = await BlobCleanupService(session_factory, blobs).run(limit)
    print(f"Checked: {result.checked}", file=out)
    print(f"Deleted: {result.deleted}", file=out)
    print(f"Failed: {result.failed}", file=out)
    return 0 if result.failed == 0 else 1


async def run_worker(
    settings: Settings,
    registry: AdapterRegistry | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    once: bool = True,
    poll_seconds: float | None = None,
    max_jobs: int | None = None,
) -> int:
    """Run queued ingestion jobs and print each result. Returns the exit code.

    With once, at most one job runs, and having no job is not an error.
    Otherwise the worker keeps going until it is stopped or has run max_jobs.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    async with _database(settings) as session_factory, _adapters(registry) as adapters:
        worker = IngestionWorker(session_factory, IngestionExecutor(session_factory, adapters))

        async def work() -> bool | None:
            await recover_stale_ingestion_jobs(session_factory, utc_now(), RECOVERY_LIMIT)
            result = await worker.run_once()
            if result.job is None:
                return None
            _print_ingestion_job(result.job, out)
            if result.lease_lost:
                print(LEASE_LOST_MESSAGE, file=out)
                return False
            return result.job.status is IngestionJobStatus.COMPLETED

        return await _run_jobs(
            work,
            "No ingestion job available.",
            out,
            once=once,
            poll_seconds=poll_seconds,
            max_jobs=max_jobs,
        )


async def run_processing_worker(
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    once: bool = True,
    poll_seconds: float | None = None,
    max_jobs: int | None = None,
) -> int:
    """Parse queued files and print each result. Returns the exit code.

    With once, at most one job runs, and having no job is not an error.
    Otherwise the worker keeps going until it is stopped or has run max_jobs.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1
    if settings.blob_dir is None:
        print(NO_BLOB_DIR_ERROR, file=err)
        return 1

    blobs = LocalBlobStore(settings.blob_dir)
    async with _database(settings) as session_factory:
        processor = DocumentProcessor(
            session_factory,
            blobs,
            create_default_parser_registry(),
            embedding_target=local_embedding_target(settings),
        )
        worker = DocumentProcessingWorker(session_factory, processor)

        async def work() -> bool | None:
            async with session_factory() as session:
                await DocumentProcessingJobRepository(session).recover_stale(
                    utc_now(), RECOVERY_LIMIT
                )
                await session.commit()
            result = await worker.run_once()
            if result.job is None:
                return None
            _print_processing_job(result.job, out)
            if result.lease_lost:
                print(LEASE_LOST_MESSAGE, file=out)
                return False
            return result.job.status is ProcessingJobStatus.COMPLETED

        return await _run_jobs(
            work,
            "No document processing job available.",
            out,
            once=once,
            poll_seconds=poll_seconds,
            max_jobs=max_jobs,
        )


async def _run_jobs(
    work: Callable[[], Awaitable[bool | None]],
    no_work_message: str,
    out: TextIO,
    *,
    once: bool,
    poll_seconds: float | None,
    max_jobs: int | None,
) -> int:
    """Run jobs with work(), which returns None when there was no job.

    In once mode the exit code is 1 when the job failed. A long running worker
    keeps going after a failed job, so its exit code only says whether it
    stopped normally.
    """
    if once:
        completed = await work()
        if completed is None:
            print(no_work_message, file=out)
            return 0
        return 0 if completed else 1

    async def handled_a_job() -> bool:
        return await work() is not None

    loop = WorkerLoop(
        handled_a_job,
        poll_seconds=DEFAULT_POLL_SECONDS if poll_seconds is None else poll_seconds,
        max_jobs=max_jobs,
    )

    def request_stop() -> None:
        print(STOPPING_MESSAGE, file=out)
        loop.stop()

    with stop_on_signals(request_stop):
        jobs = await loop.run()
    print(f"Jobs handled: {jobs}", file=out)
    return 0


def _print_ingestion_job(job: IngestionJob, out: TextIO) -> None:
    print(f"Job: {job.id}", file=out)
    print(f"Status: {job.status}", file=out)
    if job.last_error:
        print(f"Error: {job.last_error}", file=out)


def _print_processing_job(job: DocumentProcessingJob, out: TextIO) -> None:
    print(f"Job: {job.id}", file=out)
    print(f"Status: {job.status}", file=out)
    print(f"Document: {job.document_id}", file=out)
    if job.last_error:
        print(f"Error: {job.last_error}", file=out)


async def import_file(
    source_id: uuid.UUID,
    path: Path,
    settings: Settings,
    content_type: str | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Store a local file and queue it for processing. Returns the exit code.

    The file is not parsed here. run-processing-worker does that later.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1
    if settings.blob_dir is None:
        print(NO_BLOB_DIR_ERROR, file=err)
        return 1
    if not path.is_file():
        print(f"Error: File was not found: {path}", file=err)
        return 1
    content_type = content_type or MIME_TYPES.guess_type(path.name)[0]
    if content_type is None:
        print(
            f"Error: Could not tell the content type of {path.name}. Use --content-type.", file=err
        )
        return 1
    # Checked before reading, so a huge file is never loaded into memory.
    if path.stat().st_size > MAX_FILE_BYTES:
        print(f"Error: File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.", file=err)
        return 1

    data = path.read_bytes()
    blobs = LocalBlobStore(settings.blob_dir)
    async with _database(settings) as session_factory, session_factory() as session:
        try:
            imported = await FileImportService(session, blobs).import_file(
                source_id, filename=path.name, content_type=content_type, data=data
            )
        except SignalScopeError as error:
            print(f"Error: {error}", file=err)
            return 1
    print(f"Document: {imported.document.id}", file=out)
    print(f"Asset: {imported.asset.id}", file=out)
    print(f"Processing job: {imported.job.id}", file=out)
    return 0


@asynccontextmanager
async def _database(settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_database_engine(settings)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


@asynccontextmanager
async def _adapters(registry: AdapterRegistry | None) -> AsyncIterator[AdapterRegistry]:
    """Use the given registry, or the real adapters with an HTTP client."""
    if registry is not None:
        yield registry
        return
    async with HttpFetcher() as fetcher:
        yield build_registry(fetcher)


async def _ingest(
    source_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    registry: AdapterRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    async with session_factory() as session:
        source = await SourceRepository(session).get(source_id)
        if source is None:
            print("Error: Source was not found.", file=err)
            return 1
        # Checked before a run is created, so a wrong source leaves no failed run behind.
        try:
            registry.get(source.type)
        except UnsupportedSourceTypeError as error:
            print(f"Error: {error}", file=err)
            return 1
        run = await IngestionRunService(session).create(source.id)

    run = await IngestionExecutor(session_factory, registry).execute(run.id)
    _print_run(run, out)
    return 0 if run.status is IngestionStatus.COMPLETED else 1


def _print_run(run: IngestionRun, out: TextIO) -> None:
    print(f"Run: {run.id}", file=out)
    print(f"Status: {run.status}", file=out)
    print(f"Items: {run.items_seen}", file=out)
    print(f"Created: {run.documents_created}", file=out)
    print(f"Duplicates: {run.duplicates_skipped}", file=out)
    if run.error_message:
        print(f"Error: {run.error_message}", file=out)
