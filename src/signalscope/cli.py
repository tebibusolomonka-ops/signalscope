import argparse
import asyncio
import getpass
import importlib.util
import math
import mimetypes
import os
import sys
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TextIO

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.claims.gliner2 import Gliner2ClaimProvider
from signalscope.claims.provider import ClaimExtractionProvider
from signalscope.claims.registry import ClaimExtractorRegistry
from signalscope.claims.runtime import create_claim_extractor_registry
from signalscope.core.errors import (
    ConflictError,
    InvalidInputError,
    NotFoundError,
    SignalScopeError,
)
from signalscope.core.exports import ExportFormat
from signalscope.core.logging import configure_logging
from signalscope.core.settings import Settings, SettingsError, load_settings
from signalscope.db.engine import create_database_engine
from signalscope.db.session import create_session_factory
from signalscope.domain.blobs.cleanup import BlobCleanupService
from signalscope.domain.claims.job import ClaimExtractionJobStatus
from signalscope.domain.claims.job_repository import ClaimExtractionJobRepository
from signalscope.domain.claims.queue import ClaimExtractionQueueService
from signalscope.domain.claims.worker import ClaimExtractionWorker
from signalscope.domain.documents.files import MAX_FILE_BYTES
from signalscope.domain.entities.job import EntityExtractionJobStatus
from signalscope.domain.entities.job_repository import EntityExtractionJobRepository
from signalscope.domain.entities.queue import EntityExtractionQueueService
from signalscope.domain.entities.worker import EntityExtractionWorker
from signalscope.domain.events.job import EventExtractionJobStatus
from signalscope.domain.events.job_repository import EventExtractionJobRepository
from signalscope.domain.events.linking import EventLinkingResult, EventLinkingService
from signalscope.domain.events.queue import EventExtractionQueueService
from signalscope.domain.events.worker import EventExtractionWorker
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
from signalscope.domain.investigations.export import (
    InvestigationExportService,
    investigation_markdown,
)
from signalscope.domain.organizations.invitation_cleanup import InvitationCleanupService
from signalscope.domain.processing.file_import import FileImportService
from signalscope.domain.processing.job_repository import DocumentProcessingJobRepository
from signalscope.domain.processing.model import DocumentProcessingJob, ProcessingJobStatus
from signalscope.domain.processing.processor import DocumentProcessor
from signalscope.domain.processing.worker import DocumentProcessingWorker
from signalscope.domain.retention.service import AuditRetentionService
from signalscope.domain.search.embedding_job_repository import EmbeddingJobRepository
from signalscope.domain.search.embedding_queue import EmbeddingQueueService
from signalscope.domain.search.embedding_worker import EmbeddingWorker
from signalscope.domain.sources.model import SourceType
from signalscope.domain.sources.repository import SourceRepository
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.domain.tenancy.assignment import LegacySourceAssignmentService
from signalscope.domain.users.authentication import AuthenticationService
from signalscope.domain.users.passwords import PasswordHasher
from signalscope.domain.users.session_cleanup import SessionCleanupService
from signalscope.embeddings.local import LocalEmbeddingsNotInstalledError
from signalscope.embeddings.models import MULTILINGUAL_E5_SMALL
from signalscope.embeddings.provider import EmbeddingInputRole, EmbeddingProvider, embed
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.embeddings.runtime import create_embedding_registry, local_embedding_target
from signalscope.entities.local import LocalEntitiesNotInstalledError
from signalscope.entities.registry import EntityExtractorRegistry
from signalscope.entities.runtime import create_entity_extractor_registry, local_entity_model
from signalscope.evaluation.dataset import EvaluationDataError
from signalscope.evaluation.extraction.claims import evaluate_claims
from signalscope.evaluation.extraction.events import evaluate_events
from signalscope.evaluation.extraction.gates import (
    ExtractionGate,
    check_extraction_gates,
    format_extraction_gate_results,
    load_extraction_gates,
)
from signalscope.evaluation.extraction.loader import load_extraction_dataset
from signalscope.evaluation.extraction.relations import evaluate_relations
from signalscope.evaluation.extraction.report import (
    extraction_report_data,
    format_extraction_scores,
)
from signalscope.evaluation.extraction.scoring import ExtractionScore
from signalscope.evaluation.gates import (
    QualityGate,
    check_gates,
    format_gate_results,
    load_quality_gates,
)
from signalscope.evaluation.json_report import report_data, write_json_report
from signalscope.evaluation.loader import load_dataset
from signalscope.evaluation.report import format_reports
from signalscope.evaluation.retrieval import (
    DEFAULT_KS,
    check_ks,
    evaluate_hybrid,
    evaluate_lexical,
    evaluate_reranked,
    evaluate_semantic,
)
from signalscope.events.gliner2 import EVENT_RECORD, EVENT_SCHEMA, Gliner2EventProvider
from signalscope.events.provider import EventExtractionProvider
from signalscope.events.registry import EventExtractorRegistry
from signalscope.events.runtime import create_event_extractor_registry
from signalscope.extraction.gliner2 import (
    Gliner2StructuredBackend,
    LocalStructuredNotInstalledError,
)
from signalscope.extraction.runtime import create_structured_backend, local_structured_model
from signalscope.ingestion.http import HttpFetcher
from signalscope.ingestion.rss import RssIngestionAdapter
from signalscope.ingestion.web import WebIngestionAdapter
from signalscope.parsing.docx_document import DOCX_CONTENT_TYPE
from signalscope.parsing.registry import create_default_parser_registry
from signalscope.relations.gliner2 import (
    RELATION_OUTPUT,
    RELATION_TYPES,
    Gliner2RelationProvider,
)
from signalscope.relations.provider import RelationExtractionProvider
from signalscope.reranking.local import LocalRerankingNotInstalledError
from signalscope.reranking.models import MMARCO_MINILM
from signalscope.reranking.provider import RerankerProvider
from signalscope.reranking.runtime import create_reranker_registry
from signalscope.research.citations import validate_citations
from signalscope.research.context import context_text
from signalscope.research.evidence import ResearchEvidence
from signalscope.research.generation import (
    AnswerRequest,
    ResearchAnswerGenerator,
    generate_answer,
)
from signalscope.research.local import LocalAnswersNotInstalledError
from signalscope.research.runtime import create_answer_generator_registry
from signalscope.storage.local import LocalBlobStore
from signalscope.workers.runner import DEFAULT_POLL_SECONDS, WorkerLoop
from signalscope.workers.shutdown import stop_on_signals

DEFAULT_SCHEDULE_LIMIT = 100
DEFAULT_CLEANUP_LIMIT = 100
DEFAULT_SESSION_CLEANUP_LIMIT = 1000
DEFAULT_AUDIT_CLEANUP_LIMIT = 1000
DEFAULT_LINK_EVENTS_LIMIT = 1000
# Events linked per transaction batch by link-events.
LINK_EVENTS_BATCH = 200
NO_DATABASE_ERROR = "Error: Database URL is not configured. Set SIGNALSCOPE_DATABASE_URL."
NO_BLOB_DIR_ERROR = "Error: Blob directory is not configured. Set SIGNALSCOPE_BLOB_DIR."
# Stale jobs put back in the queue before each claim.
RECOVERY_LIMIT = 10
LEASE_LOST_MESSAGE = "Lease lost: another worker took the job over."
STOPPING_MESSAGE = "Stopping after the current job."
EVALUATION_MODES = ("lexical", "semantic", "hybrid", "reranked")
EXTRACTION_MODES = ("event", "claim", "relation")
LOCAL_ENTITIES_DISABLED_ERROR = (
    "Error: Local entity extraction is not enabled. Set SIGNALSCOPE_LOCAL_ENTITIES_ENABLED=true."
)
LOCAL_STRUCTURED_DISABLED_ERROR = (
    "Error: Local structured extraction is not enabled. "
    "Set SIGNALSCOPE_LOCAL_STRUCTURED_ENABLED=true."
)
LOCAL_ANSWERS_DISABLED_ERROR = (
    "Error: Local answers are not enabled. Set SIGNALSCOPE_LOCAL_ANSWERS_ENABLED=true."
)
SMOKE_QUESTION = "How much electricity did offshore wind farms produce?"
# A neutral sentence for the structured model smoke check.
STRUCTURED_SMOKE_TEXT = "Maria Lopes works for Northwind Energy, which opened a wind farm."
LOCAL_RERANKING_DISABLED = (
    "Local reranking is not enabled. Set SIGNALSCOPE_LOCAL_RERANKING_ENABLED=true."
)
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
        return asyncio.run(
            import_file(
                args.source_id,
                args.path,
                settings,
                args.content_type,
                organization_id=args.organization_id,
            )
        )
    if args.command == "cleanup-blobs":
        return asyncio.run(cleanup_blobs(args.limit, settings))
    if args.command == "evaluate-retrieval":
        return asyncio.run(
            evaluate_retrieval(
                args.dataset,
                settings,
                mode=args.mode,
                ks=args.k,
                json_output=args.json_output,
                quality_gates=args.quality_gates,
            )
        )
    if args.command == "evaluate-extraction":
        return asyncio.run(
            evaluate_extraction(
                args.dataset,
                settings,
                mode=args.mode,
                json_output=args.json_output,
                quality_gates=args.quality_gates,
            )
        )
    if args.command == "check-embedding-model":
        return asyncio.run(check_embedding_model(settings))
    if args.command == "check-structured-model":
        return asyncio.run(check_structured_model(settings))
    if args.command == "check-answer-model":
        return asyncio.run(check_answer_model(settings))
    if args.command == "queue-embeddings":
        return asyncio.run(
            queue_embeddings(settings, document_id=args.document_id, limit=args.limit)
        )
    if args.command == "queue-entities":
        return asyncio.run(queue_entities(settings, document_id=args.document_id, limit=args.limit))
    if args.command == "queue-events":
        return asyncio.run(queue_events(settings, document_id=args.document_id, limit=args.limit))
    if args.command == "create-user":
        return asyncio.run(
            create_user(
                settings,
                args.email,
                display_name=args.display_name,
                system_admin=args.system_admin,
                password_stdin=args.password_stdin,
            )
        )
    if args.command == "assign-source-organization":
        return asyncio.run(
            assign_source_organization(args.source_id, args.organization_id, settings)
        )
    if args.command == "cleanup-auth-sessions":
        return asyncio.run(cleanup_auth_sessions(args.limit, settings))
    if args.command == "cleanup-organization-invitations":
        return asyncio.run(cleanup_organization_invitations(args.limit, settings))
    if args.command == "cleanup-security-audit":
        return asyncio.run(
            cleanup_security_audit(args.organization_id, args.limit, settings, apply=args.apply)
        )
    if args.command == "export-investigation":
        return asyncio.run(
            export_investigation(
                args.investigation_id,
                settings,
                export_format=args.format,
                output=args.output,
                overwrite=args.overwrite,
            )
        )
    if args.command == "link-events":
        return asyncio.run(link_events(settings, limit=args.limit))
    if args.command == "queue-claims":
        return asyncio.run(queue_claims(settings, document_id=args.document_id, limit=args.limit))
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
        if args.command == "run-entity-worker":
            return asyncio.run(run_entity_worker(settings, **loop_options))
        if args.command == "run-event-worker":
            return asyncio.run(run_event_worker(settings, **loop_options))
        if args.command == "run-claim-worker":
            return asyncio.run(run_claim_worker(settings, **loop_options))
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
    import_command.add_argument(
        "--organization-id",
        type=uuid.UUID,
        default=None,
        help="refuse the import unless the source belongs to this organization",
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

    entity_backlog = commands.add_parser(
        "queue-entities", help="queue entity extraction jobs for chunks not read yet"
    )
    entity_backlog.add_argument(
        "--document-id", type=uuid.UUID, default=None, help="only this document (default: all)"
    )
    entity_backlog.add_argument(
        "--limit", type=positive_int, default=None, help="most jobs to create (default: no limit)"
    )

    event_backlog = commands.add_parser(
        "queue-events", help="queue event extraction jobs for chunks not read yet"
    )
    event_backlog.add_argument(
        "--document-id", type=uuid.UUID, default=None, help="only this document (default: all)"
    )
    event_backlog.add_argument(
        "--limit", type=positive_int, default=None, help="most jobs to create (default: no limit)"
    )

    user_command = commands.add_parser(
        "create-user", help="create an account; the password is asked for, never given as an option"
    )
    user_command.add_argument("email", help="the email address to sign in with")
    user_command.add_argument(
        "--display-name", default=None, help="the name shown for the user (default: from the email)"
    )
    user_command.add_argument(
        "--system-admin", action="store_true", help="give the account full admin rights"
    )
    user_command.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the password from the first line of standard input, for automation",
    )

    assignment = commands.add_parser(
        "assign-source-organization",
        help="move a legacy source and its content into an organization, once",
    )
    assignment.add_argument("source_id", type=uuid.UUID, help="ID of a source without one")
    assignment.add_argument("organization_id", type=uuid.UUID, help="ID of the organization")

    session_cleanup = commands.add_parser(
        "cleanup-auth-sessions", help="delete login sessions that expired or were revoked long ago"
    )
    session_cleanup.add_argument(
        "--limit",
        type=positive_int,
        default=DEFAULT_SESSION_CLEANUP_LIMIT,
        help=f"most sessions to delete (default: {DEFAULT_SESSION_CLEANUP_LIMIT})",
    )

    audit_cleanup = commands.add_parser(
        "cleanup-security-audit",
        help="show, or with --apply delete, audit events older than an organization's policy",
    )
    audit_cleanup.add_argument(
        "--organization-id", type=uuid.UUID, required=True, help="ID of the organization"
    )
    audit_cleanup.add_argument(
        "--limit",
        type=positive_int,
        default=DEFAULT_AUDIT_CLEANUP_LIMIT,
        help=f"most events to delete (default: {DEFAULT_AUDIT_CLEANUP_LIMIT})",
    )
    audit_cleanup.add_argument(
        "--apply", action="store_true", help="delete the events; without it nothing is deleted"
    )

    invitation_cleanup = commands.add_parser(
        "cleanup-organization-invitations",
        help="delete invitations that were used, revoked or expired long ago",
    )
    invitation_cleanup.add_argument(
        "--limit",
        type=positive_int,
        default=DEFAULT_SESSION_CLEANUP_LIMIT,
        help=f"most invitations to delete (default: {DEFAULT_SESSION_CLEANUP_LIMIT})",
    )

    export_command = commands.add_parser(
        "export-investigation", help="write a saved investigation as JSON or Markdown"
    )
    export_command.add_argument("investigation_id", type=uuid.UUID, help="ID of the investigation")
    export_command.add_argument(
        "--format",
        type=ExportFormat,
        choices=list(ExportFormat),
        default=ExportFormat.JSON,
        help="json or markdown (default: json)",
    )
    export_command.add_argument(
        "--output", type=Path, default=None, help="write to this file (default: standard output)"
    )
    export_command.add_argument(
        "--overwrite", action="store_true", help="replace the output file if it exists"
    )

    linking = commands.add_parser(
        "link-events", help="put events that are in no cluster yet into event clusters"
    )
    linking.add_argument(
        "--limit",
        type=positive_int,
        default=DEFAULT_LINK_EVENTS_LIMIT,
        help=f"most events to check (default: {DEFAULT_LINK_EVENTS_LIMIT})",
    )

    claim_backlog = commands.add_parser(
        "queue-claims", help="queue claim extraction jobs for chunks not read yet"
    )
    claim_backlog.add_argument(
        "--document-id", type=uuid.UUID, default=None, help="only this document (default: all)"
    )
    claim_backlog.add_argument(
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
    evaluation.add_argument(
        "--json-output", type=Path, default=None, help="also write the results to this JSON file"
    )
    evaluation.add_argument(
        "--quality-gates",
        type=Path,
        default=None,
        help="JSON file of minimum scores; the exit code is 1 when one is missed",
    )

    extraction = commands.add_parser(
        "evaluate-extraction", help="score event, claim and relation extraction on a dataset file"
    )
    extraction.add_argument("dataset", type=Path, help="the dataset JSON file")
    extraction.add_argument(
        "--mode",
        choices=[*EXTRACTION_MODES, "all"],
        default="all",
        help="what to score (default: all)",
    )
    extraction.add_argument(
        "--json-output", type=Path, default=None, help="also write the results to this JSON file"
    )
    extraction.add_argument(
        "--quality-gates",
        type=Path,
        default=None,
        help="JSON file of minimum scores; the exit code is 1 when one is missed",
    )

    commands.add_parser(
        "check-embedding-model", help="load the local model and embed one query and one passage"
    )

    commands.add_parser(
        "check-structured-model",
        help="load the local GLiNER2 model and run one structured and one relation extraction",
    )

    commands.add_parser(
        "check-answer-model", help="load the local answer model and answer one small question"
    )

    worker = commands.add_parser("run-worker", help="run queued ingestion jobs")
    _add_worker_options(worker)

    processing = commands.add_parser("run-processing-worker", help="parse queued imported files")
    _add_worker_options(processing)

    entity_worker = commands.add_parser(
        "run-entity-worker", help="find entities in queued chunks with the local model"
    )
    _add_worker_options(entity_worker)

    event_worker = commands.add_parser(
        "run-event-worker", help="find events in queued chunks with the local model"
    )
    _add_worker_options(event_worker)

    claim_worker = commands.add_parser(
        "run-claim-worker", help="find claims in queued chunks with the local model"
    )
    _add_worker_options(claim_worker)

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
    is_worker = args.command in (
        "run-worker",
        "run-processing-worker",
        "run-embedding-worker",
        "run-entity-worker",
        "run-event-worker",
        "run-claim-worker",
    )
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


async def queue_entities(
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    document_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> int:
    """Queue entity extraction jobs for existing chunks and print the counts.

    Returns the exit code. Nothing is loaded: the model only runs in the worker.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    model = local_entity_model(settings)
    if model is None:
        print(LOCAL_ENTITIES_DISABLED_ERROR, file=err)
        return 1
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    async with _database(settings) as session_factory:
        try:
            result = await EntityExtractionQueueService(session_factory).queue_backlog(
                model.provider, model.model, document_id=document_id, limit=limit
            )
        except NotFoundError as error:
            print(f"Error: {error}", file=err)
            return 1
    print(f"Chunks checked: {result.chunks_seen}", file=out)
    print(f"Jobs created: {result.jobs_created}", file=out)
    print(f"Already extracted: {result.already_extracted}", file=out)
    print(f"Already queued: {result.already_queued}", file=out)
    return 0


async def queue_events(
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    document_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> int:
    """Queue event extraction jobs for existing chunks and print the counts.

    Returns the exit code. Nothing is loaded: the model only runs in the worker.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    model = local_structured_model(settings)
    if model is None:
        print(LOCAL_STRUCTURED_DISABLED_ERROR, file=err)
        return 1
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    async with _database(settings) as session_factory:
        try:
            result = await EventExtractionQueueService(session_factory).queue_backlog(
                *model, document_id=document_id, limit=limit
            )
        except NotFoundError as error:
            print(f"Error: {error}", file=err)
            return 1
    print(f"Chunks checked: {result.chunks_seen}", file=out)
    print(f"Jobs created: {result.jobs_created}", file=out)
    print(f"Already extracted: {result.already_extracted}", file=out)
    print(f"Already queued: {result.already_queued}", file=out)
    return 0


async def assign_source_organization(
    source_id: uuid.UUID,
    organization_id: uuid.UUID,
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Give a legacy source an organization and print what moved. Returns the exit code.

    Only a source without an organization can be assigned. Its events leave
    their legacy clusters and are linked again inside the organization.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1
    async with _database(settings) as session_factory:
        try:
            result = await LegacySourceAssignmentService(session_factory).assign(
                source_id, organization_id
            )
        except SignalScopeError as error:
            print(f"Error: {error}", file=err)
            return 1
    print(f"Source: {result.source_id}", file=out)
    print(f"Organization: {result.organization_id}", file=out)
    print(f"Documents affected: {result.documents}", file=out)
    print(f"Events relinked: {result.events_relinked}", file=out)
    print(f"Research sessions assigned: {result.research_sessions}", file=out)
    return 0


async def cleanup_auth_sessions(
    limit: int,
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    clock: Clock = utc_now,
) -> int:
    """Delete old expired and revoked sessions and print the counts. Returns the exit code.

    Sessions are kept for SIGNALSCOPE_AUTH_SESSION_RETENTION_DAYS after they end.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    async with _database(settings) as session_factory, session_factory() as session:
        result = await SessionCleanupService(session, clock).run(
            settings.auth_session_retention_days, limit
        )
    print(f"Checked: {result.checked}", file=out)
    print(f"Deleted: {result.deleted}", file=out)
    return 0


async def cleanup_security_audit(
    organization_id: uuid.UUID,
    limit: int,
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    apply: bool = False,
    clock: Clock = utc_now,
) -> int:
    """Preview, or with apply delete, an organization's expired audit events.

    Uses the retention policy a system admin set; without one nothing is
    deleted. The command runs as a local administrator. Event contents are
    never printed. Returns the exit code.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    async with _database(settings) as session_factory, session_factory() as session:
        service = AuditRetentionService(session, clock)
        try:
            preview = await service.preview(None, organization_id)
            deleted = 0
            if apply and preview.retention_days is not None:
                deleted = (await service.cleanup(None, organization_id, limit)).deleted_count
        except SignalScopeError as error:
            print(f"Error: {error}", file=err)
            return 1
    days = "indefinite" if preview.retention_days is None else str(preview.retention_days)
    print(f"Organization: {organization_id}", file=out)
    print(f"Retention days: {days}", file=out)
    print(f"Eligible: {preview.eligible_count}", file=out)
    if apply:
        print(f"Deleted: {deleted}", file=out)
    else:
        print("Deleted: 0 (preview only; add --apply to delete)", file=out)
    return 0


async def cleanup_organization_invitations(
    limit: int,
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    clock: Clock = utc_now,
) -> int:
    """Delete old used, revoked and expired invitations and print the counts.

    Returns the exit code. No email address or token is printed.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    async with _database(settings) as session_factory, session_factory() as session:
        result = await InvitationCleanupService(session, clock).run(
            settings.organization_invitation_retention_days, limit
        )
    print(f"Checked: {result.checked}", file=out)
    print(f"Deleted: {result.deleted}", file=out)
    return 0


async def create_user(
    settings: Settings,
    email: str,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    display_name: str | None = None,
    system_admin: bool = False,
    password_stdin: bool = False,
    stdin: TextIO | None = None,
    ask_password: Callable[[str], str] = getpass.getpass,
    hasher: PasswordHasher | None = None,
) -> int:
    """Create an account. Works whether or not SIGNALSCOPE_AUTH_ENABLED is on.

    The password is asked for twice without echo, or read from the first line
    of standard input. It is never an option, so it cannot end up in shell
    history or process lists, and it is never printed. Returns the exit code.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1
    if password_stdin:
        password = (stdin or sys.stdin).readline().rstrip("\r\n")
    else:
        password = ask_password("Password: ")
        if ask_password("Repeat password: ") != password:
            print("Error: The passwords do not match.", file=err)
            return 1
    name = display_name if display_name is not None else email.strip().split("@")[0]

    async with _database(settings) as session_factory, session_factory() as session:
        try:
            user = await AuthenticationService(session, hasher).create_user(
                email, name, password, is_system_admin=system_admin
            )
        except (ConflictError, InvalidInputError) as error:
            print(f"Error: {error}", file=err)
            return 1
    print(f"User ID: {user.id}", file=out)
    print(f"Email: {user.email}", file=out)
    print(f"System admin: {'yes' if user.is_system_admin else 'no'}", file=out)
    return 0


async def export_investigation(
    investigation_id: uuid.UUID,
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    export_format: ExportFormat = ExportFormat.JSON,
    output: Path | None = None,
    overwrite: bool = False,
) -> int:
    """Export a saved investigation to standard output or a file. Returns the exit code.

    A file is written in full first and then moved into place, so it is never
    left half written. An existing file is only replaced with overwrite.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if output is not None and output.exists() and not overwrite:
        print(f"Error: {output} already exists. Use --overwrite to replace it.", file=err)
        return 1
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    async with _database(settings) as session_factory, session_factory() as session:
        try:
            export = await InvestigationExportService(session).export(investigation_id)
        except NotFoundError as error:
            print(f"Error: {error}", file=err)
            return 1
    if export_format is ExportFormat.MARKDOWN:
        text = investigation_markdown(export)
    else:
        text = export.model_dump_json(indent=2) + "\n"
    if output is None:
        print(text, end="", file=out)
        return 0
    try:
        _write_atomically(output, text)
    except OSError as error:
        print(f"Error: Cannot write {output}: {error.strerror}", file=err)
        return 1
    print(f"Wrote {output}", file=out)
    return 0


def _write_atomically(path: Path, text: str) -> None:
    """Write text to a temporary file next to path, then move it over path."""
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as file:
            file.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


async def link_events(
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    limit: int = DEFAULT_LINK_EVENTS_LIMIT,
) -> int:
    """Link events that are in no cluster yet, and print the counts.

    Repairs events made before automatic linking, or left unclustered when
    linking failed. Checks at most limit events, oldest first, so one run is
    always bounded. Returns the exit code.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    total = EventLinkingResult()
    async with _database(settings) as session_factory:
        service = EventLinkingService(session_factory)
        while total.events_checked < limit:
            size = min(LINK_EVENTS_BATCH, limit - total.events_checked)
            result = await service.link_unclustered(size)
            total = EventLinkingResult(
                events_checked=total.events_checked + result.events_checked,
                events_linked=total.events_linked + result.events_linked,
                clusters_created=total.clusters_created + result.clusters_created,
            )
            # A short batch means the backlog is empty. A batch that links nothing
            # would only find the same events again.
            if result.events_checked < size or result.events_linked == 0:
                break
    print(f"Events checked: {total.events_checked}", file=out)
    print(f"Events linked: {total.events_linked}", file=out)
    print(f"Clusters created: {total.clusters_created}", file=out)
    return 0


async def queue_claims(
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    document_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> int:
    """Queue claim extraction jobs for existing chunks and print the counts.

    Returns the exit code. Nothing is loaded: the model only runs in the worker.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    model = local_structured_model(settings)
    if model is None:
        print(LOCAL_STRUCTURED_DISABLED_ERROR, file=err)
        return 1
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    async with _database(settings) as session_factory:
        try:
            result = await ClaimExtractionQueueService(session_factory).queue_backlog(
                *model, document_id=document_id, limit=limit
            )
        except NotFoundError as error:
            print(f"Error: {error}", file=err)
            return 1
    print(f"Chunks checked: {result.chunks_seen}", file=out)
    print(f"Jobs created: {result.jobs_created}", file=out)
    print(f"Already extracted: {result.already_extracted}", file=out)
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


async def run_entity_worker(
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    extractors: EntityExtractorRegistry | None = None,
    once: bool = True,
    poll_seconds: float | None = None,
    max_jobs: int | None = None,
) -> int:
    """Find entities in queued chunks and print each result. Returns the exit code.

    Without extractors, the local model from settings is used. It is only
    loaded when a job needs it, so an empty queue never loads it.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if extractors is None:
        extractors = _local_entities(settings, err)
        if extractors is None:
            return 1
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    async with _database(settings) as session_factory:
        worker = EntityExtractionWorker(session_factory, extractors)

        async def work() -> bool | None:
            async with session_factory() as session:
                await EntityExtractionJobRepository(session).recover_stale(
                    utc_now(), RECOVERY_LIMIT
                )
                await session.commit()
            result = await worker.run_once()
            if result.job is None:
                return None
            print(f"Job: {result.job.id}", file=out)
            if result.lease_lost:
                print(LEASE_LOST_MESSAGE, file=out)
                return False
            print(f"Status: {result.job.status}", file=out)
            print(f"Mentions: {result.mention_count}", file=out)
            if result.job.last_error:
                print(f"Error: {result.job.last_error}", file=out)
            return result.job.status is EntityExtractionJobStatus.COMPLETED

        return await _run_jobs(
            work,
            "No entity extraction job available.",
            out,
            once=once,
            poll_seconds=poll_seconds,
            max_jobs=max_jobs,
        )


async def run_event_worker(
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    extractors: EventExtractorRegistry | None = None,
    once: bool = True,
    poll_seconds: float | None = None,
    max_jobs: int | None = None,
) -> int:
    """Find events in queued chunks and print each result. Returns the exit code.

    Without extractors, the local GLiNER2 model from settings is used. It is
    only loaded when a job needs it, so an empty queue never loads it.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if extractors is None:
        if not _local_structured_ready(settings, err):
            return 1
        extractors = create_event_extractor_registry(settings)
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    async with _database(settings) as session_factory:
        worker = EventExtractionWorker(session_factory, extractors)

        async def work() -> bool | None:
            async with session_factory() as session:
                await EventExtractionJobRepository(session).recover_stale(utc_now(), RECOVERY_LIMIT)
                await session.commit()
            result = await worker.run_once()
            if result.job is None:
                return None
            print(f"Job: {result.job.id}", file=out)
            if result.lease_lost:
                print(LEASE_LOST_MESSAGE, file=out)
                return False
            print(f"Status: {result.job.status}", file=out)
            print(f"Events: {result.event_count}", file=out)
            if result.job.last_error:
                print(f"Error: {result.job.last_error}", file=out)
            return result.job.status is EventExtractionJobStatus.COMPLETED

        return await _run_jobs(
            work,
            "No event extraction job available.",
            out,
            once=once,
            poll_seconds=poll_seconds,
            max_jobs=max_jobs,
        )


async def run_claim_worker(
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    extractors: ClaimExtractorRegistry | None = None,
    once: bool = True,
    poll_seconds: float | None = None,
    max_jobs: int | None = None,
) -> int:
    """Find claims in queued chunks and print each result. Returns the exit code.

    Without extractors, the local GLiNER2 model from settings is used. It is
    only loaded when a job needs it, so an empty queue never loads it.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if extractors is None:
        if not _local_structured_ready(settings, err):
            return 1
        extractors = create_claim_extractor_registry(settings)
    if settings.database_url is None:
        print(NO_DATABASE_ERROR, file=err)
        return 1

    async with _database(settings) as session_factory:
        worker = ClaimExtractionWorker(session_factory, extractors)

        async def work() -> bool | None:
            async with session_factory() as session:
                await ClaimExtractionJobRepository(session).recover_stale(utc_now(), RECOVERY_LIMIT)
                await session.commit()
            result = await worker.run_once()
            if result.job is None:
                return None
            print(f"Job: {result.job.id}", file=out)
            if result.lease_lost:
                print(LEASE_LOST_MESSAGE, file=out)
                return False
            print(f"Status: {result.job.status}", file=out)
            print(f"Claims: {result.claim_count}", file=out)
            if result.job.last_error:
                print(f"Error: {result.job.last_error}", file=out)
            return result.job.status is ClaimExtractionJobStatus.COMPLETED

        return await _run_jobs(
            work,
            "No claim extraction job available.",
            out,
            once=once,
            poll_seconds=poll_seconds,
            max_jobs=max_jobs,
        )


def _local_structured_ready(settings: Settings, err: TextIO) -> bool:
    """Whether the local GLiNER2 model can be used. Prints why not when it cannot.

    Nothing is loaded here. The library is only looked up.
    """
    if not settings.local_structured_enabled:
        print(LOCAL_STRUCTURED_DISABLED_ERROR, file=err)
        return False
    if importlib.util.find_spec("gliner2") is None:
        print(f"Error: {LocalStructuredNotInstalledError()}", file=err)
        return False
    return True


def _local_entities(settings: Settings, err: TextIO) -> EntityExtractorRegistry | None:
    """The registry with the local entity model, or None after printing why not.

    Nothing is loaded here. The library is only looked up.
    """
    if not settings.local_entities_enabled:
        print(LOCAL_ENTITIES_DISABLED_ERROR, file=err)
        return None
    if importlib.util.find_spec("gliner") is None:
        print(f"Error: {LocalEntitiesNotInstalledError()}", file=err)
        return None
    return create_entity_extractor_registry(settings)


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
    reranker: RerankerProvider | None = None,
    json_output: Path | None = None,
    quality_gates: Path | None = None,
) -> int:
    """Score search on a dataset file and print the results. Returns the exit code.

    Semantic, hybrid and reranked modes use provider, or the local embedding
    model from settings. The reranked mode also uses reranker, or the local
    reranker. In the all mode a missing reranker skips the reranked mode, and
    the output says so. The dataset is loaded into the database only for the
    run and rolled back. With json_output the results are also written there.
    With quality_gates, the exit code is 1 when a minimum in that file is missed.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    try:
        dataset = load_dataset(path)
    except EvaluationDataError as error:
        print(f"Error: {error}", file=err)
        return 1
    modes: tuple[str, ...] = EVALUATION_MODES if mode == "all" else (mode,)
    gates = []
    if quality_gates is not None:
        try:
            gates = load_quality_gates(quality_gates, EVALUATION_MODES)
        except EvaluationDataError as error:
            print(f"Error: {error}", file=err)
            return 1
        problem = _gate_problem(gates, modes, check_ks(ks))
        if problem is not None:
            print(f"Error: {problem}", file=err)
            return 1
    skipped: dict[str, str] = {}
    if reranker is None and "reranked" in modes:
        problem = _local_reranking_problem(settings)
        if problem is None:
            reranker = create_reranker_registry(settings).get(
                MMARCO_MINILM.provider, MMARCO_MINILM.model
            )
        elif mode == "reranked":
            print(f"Error: {problem}", file=err)
            return 1
        else:
            skipped["reranked"] = problem
            modes = tuple(name for name in modes if name != "reranked")
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
            elif name == "hybrid":
                reports.append(await evaluate_hybrid(session_factory, dataset, provider, ks))
            else:
                assert reranker is not None
                reports.append(
                    await evaluate_reranked(session_factory, dataset, provider, reranker, ks)
                )
    out.write(format_reports(dataset.name, len(dataset.queries), reports, skipped))
    if json_output is not None:
        used = {report.mode for report in reports}
        data = report_data(
            dataset.name,
            len(dataset.queries),
            check_ks(ks),
            reports,
            skipped,
            embedding=provider if used - {"lexical"} else None,
            reranker=reranker if "reranked" in used else None,
        )
        try:
            write_json_report(json_output, data)
        except OSError as error:
            print(f"Error: Cannot write {json_output}: {error.strerror}", file=err)
            return 1
    if gates:
        results = check_gates(gates, reports)
        out.write(format_gate_results(results))
        if not all(result.passed for result in results):
            return 1
    return 0


def _gate_problem(
    gates: Sequence[QualityGate], modes: Sequence[str], ks: Sequence[int]
) -> str | None:
    """Why the gates cannot be checked in this run, or None."""
    for gate in gates:
        if gate.mode not in modes:
            return f"Quality gate {gate.label} needs --mode {gate.mode} or all."
        if gate.k not in ks:
            return f"Quality gate {gate.label} needs k={gate.k} in --k."
    return None


def _local_reranking_problem(settings: Settings) -> str | None:
    """Why the local reranker cannot be used, or None when it can. Nothing is loaded."""
    if not settings.local_reranking_enabled:
        return LOCAL_RERANKING_DISABLED
    if importlib.util.find_spec("sentence_transformers") is None:
        return str(LocalRerankingNotInstalledError())
    return None


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


async def evaluate_extraction(
    path: Path,
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    mode: str = "all",
    json_output: Path | None = None,
    quality_gates: Path | None = None,
    event_provider: EventExtractionProvider | None = None,
    claim_provider: ClaimExtractionProvider | None = None,
    relation_provider: RelationExtractionProvider | None = None,
) -> int:
    """Score extraction models on a local dataset and print precision, recall and F1.

    Without providers, the local GLiNER2 model is used for all three, one
    loaded copy for all. It may be downloaded the first time. The relation
    provider is experimental and nothing it finds is stored. There are no
    built-in quality targets: with quality_gates, the exit code is 1 when a
    minimum in that file is missed. Returns the exit code.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    modes = EXTRACTION_MODES if mode == "all" else (mode,)
    gates: list[ExtractionGate] = []
    try:
        dataset = load_extraction_dataset(path)
        if quality_gates is not None:
            # Read first, so a bad file fails before any model runs.
            gates = load_extraction_gates(quality_gates)
    except EvaluationDataError as error:
        print(f"Error: {error}", file=err)
        return 1
    needs_model = (
        ("event" in modes and event_provider is None)
        or ("claim" in modes and claim_provider is None)
        or ("relation" in modes and relation_provider is None)
    )
    if needs_model:
        if not _local_structured_ready(settings, err):
            return 1
        backend = create_structured_backend(settings)
        assert backend is not None
        event_provider = event_provider or Gliner2EventProvider(backend)
        claim_provider = claim_provider or Gliner2ClaimProvider(backend)
        relation_provider = relation_provider or Gliner2RelationProvider(backend)
    scores: list[ExtractionScore] = []
    try:
        if "event" in modes and event_provider is not None:
            scores.append(await evaluate_events(dataset, event_provider))
        if "claim" in modes and claim_provider is not None:
            scores.append(await evaluate_claims(dataset, claim_provider))
        if "relation" in modes and relation_provider is not None:
            scores.append(await evaluate_relations(dataset, relation_provider))
    except SignalScopeError as error:
        print(f"Error: {error}", file=err)
        return 1
    print(format_extraction_scores(dataset, scores), end="", file=out)
    if json_output is not None:
        write_json_report(json_output, extraction_report_data(dataset, scores))
    if gates:
        results = check_extraction_gates(gates, scores)
        print(format_extraction_gate_results(results), end="", file=out)
        if not all(result.passed for result in results):
            return 1
    return 0


async def check_structured_model(
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    backend: Gliner2StructuredBackend | None = None,
) -> int:
    """Load the local GLiNER2 model and run one small extraction of each kind.

    It checks that the model loads and answers in the expected shape, not that
    the answers are right. The first run downloads the model when it is not
    cached yet. Returns the exit code.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if backend is None:
        if not _local_structured_ready(settings, err):
            return 1
        backend = create_structured_backend(settings)
        assert backend is not None
    try:
        records = await backend.extract_json(STRUCTURED_SMOKE_TEXT, EVENT_SCHEMA)
        if not isinstance(records.get(EVENT_RECORD), list):
            raise SignalScopeError("Structured extraction returned no list of records.")
        relations = await backend.extract_relations(STRUCTURED_SMOKE_TEXT, RELATION_TYPES)
        if not isinstance(relations.get(RELATION_OUTPUT), Mapping):
            raise SignalScopeError("Relation extraction returned no relations object.")
    except SignalScopeError as error:
        print(f"Error: {error}", file=err)
        return 1
    print(f"Provider: {backend.provider_name}", file=out)
    print(f"Model: {backend.model_name}", file=out)
    print("Structured extraction: ok", file=out)
    print("Relation extraction: ok", file=out)
    return 0


async def check_answer_model(
    settings: Settings,
    out: TextIO | None = None,
    err: TextIO | None = None,
    *,
    generator: ResearchAnswerGenerator | None = None,
) -> int:
    """Load the local answer model, answer one question from one piece of evidence.

    The answer goes through the same citation checks as the API. The first run
    downloads the model when it is not cached yet. Prints a short summary.
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if generator is None:
        if not settings.local_answers_enabled:
            print(LOCAL_ANSWERS_DISABLED_ERROR, file=err)
            return 1
        if any(importlib.util.find_spec(name) is None for name in ("transformers", "torch")):
            print(f"Error: {LocalAnswersNotInstalledError()}", file=err)
            return 1
        generator = create_answer_generator_registry(settings).only()
    evidence = [
        ResearchEvidence(
            evidence_id="E1",
            document_id=uuid.uuid4(),
            chunk_id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            title="Energy report",
            url=None,
            excerpt=SMOKE_PASSAGE,
            text=SMOKE_PASSAGE,
            chunk_metadata={},
            scores={},
        )
    ]
    request = AnswerRequest(
        question=SMOKE_QUESTION, evidence=tuple(evidence), context_text=context_text(evidence)
    )
    try:
        answer = validate_citations(await generate_answer(generator, request), evidence)
    except SignalScopeError as error:
        print(f"Error: {error}", file=err)
        return 1
    print(f"Provider: {generator.provider_name}", file=out)
    print(f"Model: {generator.model_name}", file=out)
    print(f"Citations: {', '.join(answer.citation_ids)}", file=out)
    print("Answer generated: yes", file=out)
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
    *,
    organization_id: uuid.UUID | None = None,
) -> int:
    """Store a local file and queue it for processing. Returns the exit code.

    The file is not parsed here. run-processing-worker does that later. The
    document belongs to the source's organization, or is legacy content when
    the source has none. organization_id makes the import fail unless the
    source belongs to that organization.
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
                source_id,
                filename=path.name,
                content_type=content_type,
                data=data,
                organization_id=organization_id,
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
