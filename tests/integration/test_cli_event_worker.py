import asyncio
import hashlib
import io
import signal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fake_events import FakeEventExtractor
from signalscope.cli import run_event_worker
from signalscope.core.settings import Settings
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.events.model import Event
from signalscope.domain.events.queue import EventExtractionQueueService
from signalscope.domain.sources.model import Source, SourceType
from signalscope.events.provider import ExtractedEvent
from signalscope.events.registry import EventExtractorRegistry

pytestmark = pytest.mark.anyio

TIMEOUT_SECONDS = 10


@pytest.fixture
def settings(database_engine: AsyncEngine, migrated_database: Settings) -> Settings:
    return Settings(database_url=migrated_database.database_url)


async def queue_chunks(session_factory: async_sessionmaker[AsyncSession], *texts: str) -> None:
    chunks = [
        TextChunk(
            position=index,
            text=text,
            start_char=0,
            end_char=len(text),
            text_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
        for index, text in enumerate(texts)
    ]
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id)
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunks)
        await session.commit()
        saved = await repository.list_by_document(document.id)
    await EventExtractionQueueService(session_factory).queue_chunks(
        [chunk.id for chunk in saved], "test", "flood-words"
    )


async def run(
    settings: Settings, extractor: FakeEventExtractor, **options: Any
) -> tuple[int, str, str]:
    registry = EventExtractorRegistry()
    registry.register(extractor)
    out, err = io.StringIO(), io.StringIO()
    code = await asyncio.wait_for(
        run_event_worker(settings, out, err, extractors=registry, **options), TIMEOUT_SECONDS
    )
    return code, out.getvalue(), err.getvalue()


class UntouchableExtractor(FakeEventExtractor):
    """Stands in for a model that must not load."""

    async def extract(self, text: str) -> list[ExtractedEvent]:
        raise AssertionError("the model was used although there was no work")


async def test_no_job_does_not_use_the_model(settings: Settings) -> None:
    assert await run(settings, UntouchableExtractor()) == (
        0,
        "No event extraction job available.\n",
        "",
    )


async def test_one_job(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await queue_chunks(session_factory, "The river flooded. A flood hit the port.")

    code, out, err = await run(settings, FakeEventExtractor())

    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0].startswith("Job: ")
    assert lines[1:] == ["Status: completed", "Events: 2"]
    async with session_factory() as session:
        assert len(list(await session.scalars(select(Event)))) == 2


async def test_failed_job_exits_with_an_error(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await queue_chunks(session_factory, "The river flooded.")
    extractor = FakeEventExtractor()
    extractor.error = RuntimeError("private details")

    code, out, _ = await run(settings, extractor)

    assert code == 1
    assert "Status: failed\n" in out
    assert "private details" not in out


async def test_loop_stops_after_max_jobs(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await queue_chunks(session_factory, "Flood one.", "Flood two.", "Flood three.")

    code, out, _ = await run(
        settings, FakeEventExtractor(), once=False, poll_seconds=0.01, max_jobs=2
    )

    assert code == 0
    assert out.count("Status: completed\n") == 2
    assert out.endswith("Jobs handled: 2\n")


class SignallingExtractor(FakeEventExtractor):
    """Asks the worker to stop while it reads its first chunk."""

    async def extract(self, text: str) -> list[ExtractedEvent]:
        if not self.calls:
            signal.raise_signal(signal.SIGINT)
            # Let the event loop see the signal before the job ends.
            for _ in range(100):
                await asyncio.sleep(0)
        return await super().extract(text)


async def test_stop_signal_finishes_the_job_then_stops(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await queue_chunks(session_factory, "Flood one.", "Flood two.")

    code, out, _ = await run(
        settings, SignallingExtractor(), once=False, poll_seconds=0.01, max_jobs=5
    )

    assert code == 0
    assert "Stopping after the current job.\n" in out
    assert out.endswith("Jobs handled: 1\n")
