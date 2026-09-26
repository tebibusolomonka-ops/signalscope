import argparse
import asyncio
import importlib.util
import math
import mimetypes
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TextIO

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.errors import NotFoundError, SignalScopeError
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
from signalscope.domain.search.embedding_job_repository import EmbeddingJobRepository
from signalscope.domain.search.embedding_queue import EmbeddingQueueService
from signalscope.domain.search.embedding_worker import EmbeddingWorker
from signalscope.domain.sources.model import SourceType
from signalscope.domain.sources.repository import SourceRepository
from signalscope.domain.sources.scheduling import utc_now
from signalscope.embeddings.local import LocalEmbeddingsNotInstalledError
from signalscope.embeddings.models import MULTILINGUAL_E5_SMALL
from signalscope.embeddings.provider import EmbeddingInputRole, EmbeddingProvider, embed
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.embeddings.runtime import create_embedding_registry, local_embedding_target
from signalscope.evaluation.dataset import EvaluationDataError
from signalscope.evaluation.loader import load_dataset
from signalscope.evaluation.report import format_reports
from signalscope.evaluation.retrieval import (
    DEFAULT_KS,
    check_ks,
    evaluate_hybrid,
    evaluate_lexical,
    evaluate_semantic,
)
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
EVALUATION_MODES = ("lexical", "semantic", "hybrid")
SMOKE_QUERY = "offshore wind energy"
SMOKE_PASSAGE = "Offshore wind farms produced more electricity this year."
LOCAL_EMBEDDINGS_DISABLED_ERROR = (
    "Error: Local embeddings are not enabled. Set SIGNALSCOPE_LOCAL_EMBEDDINGS_ENABLED=true."
)

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
    if args.command == "evaluate-retrieval":
        return asyncio.run(evaluate_retrieval(args.dataset, settings, mode=args.mode, ks=args.k))
    if args.command == "check-embedding-model":
        return asyncio.run(check_embedding_model(settings))
    if args.command == "queue-embeddings":
        return asyncio.run(
            queue_embeddings(settings, document_id=args.document_id, limit=args.limit)
        )
    loop_options = {
        "once": args.once,
        "poll_seconds": args.poll_seconds,
        "max_jobs": args.max_jobs,
    }
    try:
        if args.command == "run-worker":
            return asyncio.run(run_worker(settings, **loop_options))
        if args.command == "run-embedding-worker":
            return asyncio.run(
                run_embedding_worker(settings, batch_size=args.batch_size, **loop_options)
            )
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

    backlog = commands.add_parser(
        "queue-embeddings", help="queue embedding jobs for chunks that have no current embedding"
    )
    backlog.add_argument(
        "--document-id", type=uuid.UUID, default=None, help="only this document (default: all)"
    )
    backlog.add_argument(
        "--limit", type=positive_int, default=None, help="most jobs to create (default: no limit)"
    )

    evaluation = commands.add_parser(
        "evaluate-retrieval", help="score search on a local dataset file"
    )
    evaluation.add_argument("dataset", type=Path, help="the dataset JSON file")
    evaluation.add_argument(
        "--mode",
        choices=[*EVALUATION_MODES, "all"],
        default="all",
        help="which search to score (default: all)",
    )
    evaluation.add_argument(
        "--k",
        type=evaluation_ks,
        default=list(DEFAULT_KS),
        help="comma-separated cut-offs (default: 1,5,10)",
    )

    commands.add_parser(
        "check-embedding-model", help="load the local model and embed one query and one passage"
    )

    worker = commands.add_parser("run-worker", help="run queued ingestion jobs")
    _add_worker_options(worker)

    processing = commands.add_parser("run-processing-worker", help="parse queued imported files")
    _add_worker_options(processing)

    embedding = commands.add_parser(
        "run-embedding-worker", help="embed queued chunks with the local model"
    )
    _add_worker_options(embedding)
    embedding.add_argument(
        "--batch-size",
        type=positive_int,
        default=None,
        help="most chunks per model call (default: SIGNALSCOPE_LOCAL_EMBEDDING_BATCH_SIZE)",
    )
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
    is_worker = args.command in ("run-worker", "run-processing-worker", "run-embedding-worker")
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


async def queue_embeddings(
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    document_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> int:
    """Queue embedding jobs for existing chunks and print the counts. Returns the exit code."""
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    target = local_embedding_target(settings)
    if target is None:
        print(LOCAL_EMBEDDINGS_DISABLED_ERROR, file=err)
        return 1
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    async with _database(settings) as session_factory:
        try:
            result = await EmbeddingQueueService(session_factory).queue_backlog(
                target.provider, target.model, document_id=document_id, limit=limit
            )
        except NotFoundError as error:
            print(f"Error: {error}", file=err)
            return 1
    print(f"Chunks checked: {result.chunks_seen}", file=out)
    print(f"Jobs created: {result.jobs_created}", file=out)
    print(f"Already embedded: {result.already_embedded}", file=out)
    print(f"Already queued: {result.already_queued}", file=out)
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


async def run_embedding_worker(
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    providers: EmbeddingProviderRegistry | None = None,
    batch_size: int | None = None,
    once: bool = True,
    poll_seconds: float | None = None,
    max_jobs: int | None = None,
) -> int:
    """Embed queued chunks in batches and print each result. Returns the exit code.

    Without providers, the local model from settings is used. It is only
    loaded when a batch needs it. In loop mode each batch counts as one job
    for max_jobs.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if providers is None:
        providers = _local_embeddings(settings, err)
        if providers is None:
            return 1
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    async with _database(settings) as session_factory:
        worker = EmbeddingWorker(
            session_factory,
            providers,
            batch_size=settings.local_embedding_batch_size if batch_size is None else batch_size,
        )

        async def work() -> bool | None:
            async with session_factory() as session:
                await EmbeddingJobRepository(session).recover_stale(utc_now(), RECOVERY_LIMIT)
                await session.commit()
            result = await worker.run_once()
            if not result.jobs:
                return None
            first = result.jobs[0]
            print(f"Model: {first.provider}/{first.model}", file=out)
            print(f"Jobs: {len(result.jobs)}", file=out)
            print(f"Completed: {result.completed}", file=out)
            print(f"Failed: {result.failed}", file=out)
            print(f"Lease lost: {result.lease_lost}", file=out)
            return result.failed == 0 and result.lease_lost == 0

        return await _run_jobs(
            work,
            "No embedding job available.",
            out,
            once=once,
            poll_seconds=poll_seconds,
            max_jobs=max_jobs,
        )


def _local_embeddings(settings: Settings, err: TextIO) -> EmbeddingProviderRegistry | None:
    """The registry with the local model, or None after printing why it cannot be used.

    Nothing is loaded here. The library is only looked up, so a missing extra is
    reported before any work starts.
    """
    if not settings.local_embeddings_enabled:
        print(LOCAL_EMBEDDINGS_DISABLED_ERROR, file=err)
        return None
    if importlib.util.find_spec("sentence_transformers") is None:
        print(f"Error: {LocalEmbeddingsNotInstalledError()}", file=err)
        return None
    return create_embedding_registry(settings)


def _local_provider(settings: Settings, err: TextIO) -> EmbeddingProvider | None:
    registry = _local_embeddings(settings, err)
    if registry is None:
        return None
    return registry.get(MULTILINGUAL_E5_SMALL.provider, MULTILINGUAL_E5_SMALL.model)


async def evaluate_retrieval(
    path: Path,
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    mode: str = "all",
    ks: Sequence[int] = DEFAULT_KS,
    provider: EmbeddingProvider | None = None,
) -> int:
    """Score search on a dataset file and print the results. Returns the exit code.

    Semantic and hybrid modes use provider, or the local model from settings.
    The dataset is loaded into the database only for the run and rolled back.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    try:
        dataset = load_dataset(path)
    except EvaluationDataError as error:
        print(f"Error: {error}", file=err)
        return 1
    modes = EVALUATION_MODES if mode == "all" else (mode,)
    if provider is None and modes != ("lexical",):
        provider = _local_provider(settings, err)
        if provider is None:
            return 1
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    reports = []
    async with _database(settings) as session_factory:
        for name in modes:
            if name == "lexical":
                reports.append(await evaluate_lexical(session_factory, dataset, ks))
                continue
            # Only the lexical mode can run without a provider.
            assert provider is not None
            if name == "semantic":
                reports.append(await evaluate_semantic(session_factory, dataset, provider, ks))
            else:
                reports.append(await evaluate_hybrid(session_factory, dataset, provider, ks))
    out.write(format_reports(dataset.name, len(dataset.queries), reports))
    return 0


async def check_embedding_model(
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    provider: EmbeddingProvider | None = None,
) -> int:
    """Load the local model, embed one query and one passage, and print a summary.

    The first run downloads the model when it is not cached yet.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if provider is None:
        provider = _local_provider(settings, err)
        if provider is None:
            return 1
    try:
        [query] = await embed(provider, [SMOKE_QUERY], EmbeddingInputRole.QUERY)
        [passage] = await embed(provider, [SMOKE_PASSAGE], EmbeddingInputRole.PASSAGE)
    except SignalScopeError as error:
        print(f"Error: {error}", file=err)
        return 1
    print(f"Model: {provider.provider_name}/{provider.model_name}", file=out)
    print(f"Dimensions: {provider.dimensions}", file=out)
    print(f"Query vector: {len(query)} numbers", file=out)
    print(f"Passage vector: {len(passage)} numbers", file=out)
    print(f"Cosine similarity: {_cosine(query, passage):.3f}", file=out)
    return 0


def _cosine(first: Sequence[float], second: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(first, second, strict=True))
    norms = math.sqrt(sum(a * a for a in first)) * math.sqrt(sum(b * b for b in second))
    return dot / norms if norms else 0.0


def evaluation_ks(value: str) -> list[int]:
    """Parse a comma-separated list of k values, such as 1,5,10."""
    try:
        numbers = [int(part) for part in value.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"must be whole numbers such as 1,5,10: {value!r}"
        ) from None
    try:
        return list(check_ks(numbers))
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


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
