import argparse
import asyncio
import mimetypes
import sys
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TextIO

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import SignalScopeError
from signalscope.core.logging import configure_logging
from signalscope.core.settings import Settings, SettingsError, load_settings
from signalscope.db.engine import create_database_engine
from signalscope.db.session import create_session_factory
from signalscope.domain.documents.files import MAX_FILE_BYTES
from signalscope.domain.ingestion.executor import IngestionExecutor
from signalscope.domain.ingestion.model import IngestionJobStatus, IngestionRun, IngestionStatus
from signalscope.domain.ingestion.registry import AdapterRegistry, UnsupportedSourceTypeError
from signalscope.domain.ingestion.scheduler import IngestionScheduler
from signalscope.domain.ingestion.service import IngestionRunService
from signalscope.domain.ingestion.worker import IngestionWorker
from signalscope.domain.processing.file_import import FileImportService
from signalscope.domain.processing.model import ProcessingJobStatus
from signalscope.domain.processing.processor import DocumentProcessor
from signalscope.domain.processing.worker import DocumentProcessingWorker
from signalscope.domain.sources.model import SourceType
from signalscope.domain.sources.repository import SourceRepository
from signalscope.ingestion.http import HttpFetcher
from signalscope.ingestion.rss import RssIngestionAdapter
from signalscope.ingestion.web import WebIngestionAdapter
from signalscope.parsing.docx_document import DOCX_CONTENT_TYPE
from signalscope.parsing.registry import create_default_parser_registry
from signalscope.storage.local import LocalBlobStore

DEFAULT_SCHEDULE_LIMIT = 100
NO_DATABASE_ERROR = "Error: Database URL is not configured. Set SIGNALSCOPE_DATABASE_URL."
NO_BLOB_DIR_ERROR = "Error: Blob directory is not configured. Set SIGNALSCOPE_BLOB_DIR."

# Only the types built into Python, so the guess does not depend on the machine.
MIME_TYPES = mimetypes.MimeTypes()
MIME_TYPES.add_type(DOCX_CONTENT_TYPE, ".docx")
MIME_TYPES.add_type("application/xhtml+xml", ".xhtml")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

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
    if args.command == "run-worker":
        return asyncio.run(run_worker(settings))
    return asyncio.run(run_processing_worker(settings))


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

    worker = commands.add_parser("run-worker", help="run a queued ingestion job")
    # Only one mode exists for now. The flag keeps the command clear if a loop is added.
    worker.add_argument(
        "--once", action="store_true", required=True, help="run at most one job, then exit"
    )

    processing = commands.add_parser("run-processing-worker", help="parse a queued imported file")
    processing.add_argument(
        "--once", action="store_true", required=True, help="run at most one job, then exit"
    )
    return parser


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


async def run_worker(
    settings: Settings,
    registry: AdapterRegistry | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run one queued job and print the result. Returns the exit code.

    Having no job to run is not an error.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    async with _database(settings) as session_factory, _adapters(registry) as adapters:
        executor = IngestionExecutor(session_factory, adapters)
        result = await IngestionWorker(session_factory, executor).run_once()

    if result.job is None:
        print("No ingestion job available.", file=out)
        return 0
    print(f"Job: {result.job.id}", file=out)
    print(f"Status: {result.job.status}", file=out)
    if result.job.last_error:
        print(f"Error: {result.job.last_error}", file=out)
    return 0 if result.job.status is IngestionJobStatus.COMPLETED else 1


async def run_processing_worker(
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Parse one queued file and print the result. Returns the exit code.

    Having no job to run is not an error.
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
        processor = DocumentProcessor(session_factory, blobs, create_default_parser_registry())
        result = await DocumentProcessingWorker(session_factory, processor).run_once()

    if result.job is None:
        print("No document processing job available.", file=out)
        return 0
    print(f"Job: {result.job.id}", file=out)
    print(f"Status: {result.job.status}", file=out)
    print(f"Document: {result.job.document_id}", file=out)
    if result.job.last_error:
        print(f"Error: {result.job.last_error}", file=out)
    return 0 if result.job.status is ProcessingJobStatus.COMPLETED else 1


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
