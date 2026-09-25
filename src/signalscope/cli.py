import argparse
import asyncio
import sys
import uuid
from collections.abc import Sequence
from typing import TextIO

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.core.logging import configure_logging
from signalscope.core.settings import Settings, SettingsError, load_settings
from signalscope.db.engine import create_database_engine
from signalscope.db.session import create_session_factory
from signalscope.domain.ingestion.executor import IngestionExecutor
from signalscope.domain.ingestion.model import IngestionRun, IngestionStatus
from signalscope.domain.ingestion.registry import AdapterRegistry, UnsupportedSourceTypeError
from signalscope.domain.ingestion.service import IngestionRunService
from signalscope.domain.sources.model import SourceType
from signalscope.domain.sources.repository import SourceRepository
from signalscope.ingestion.http import HttpFetcher
from signalscope.ingestion.rss import RssIngestionAdapter
from signalscope.ingestion.web import WebIngestionAdapter


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="signalscope", description="SignalScope tools.")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest-source", help="fetch new content for one source")
    ingest.add_argument("source_id", type=uuid.UUID, help="ID of the source")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except SettingsError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    configure_logging(settings)
    return asyncio.run(ingest_source(args.source_id, settings))


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
        print("Error: Database URL is not configured. Set SIGNALSCOPE_DATABASE_URL.", file=err)
        return 1

    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        if registry is not None:
            return await _ingest(source_id, session_factory, registry, out, err)
        async with HttpFetcher() as fetcher:
            return await _ingest(source_id, session_factory, build_registry(fetcher), out, err)
    finally:
        await engine.dispose()


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
