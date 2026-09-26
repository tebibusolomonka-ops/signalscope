import asyncio
import hashlib
import io
import signal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fake_entities import FakeEntityExtractor
from signalscope.cli import run_entity_worker
from signalscope.core.settings import Settings
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.queue import EntityExtractionQueueService
from signalscope.domain.sources.model import Source, SourceType
from signalscope.entities.provider import ExtractedEntityMention
from signalscope.entities.registry import EntityExtractorRegistry

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
    await EntityExtractionQueueService(session_factory).queue_chunks(
        [chunk.id for chunk in saved], "test", "known-words"
    )


async def run(
    settings: Settings, extractor: FakeEntityExtractor, **options: Any
) -> tuple[int, str, str]:
    registry = EntityExtractorRegistry()
    registry.register(extractor)
    out, err = io.StringIO(), io.StringIO()
    code = await asyncio.wait_for(
        run_entity_worker(settings, out, err, extractors=registry, **options), TIMEOUT_SECONDS
    )
    return code, out.getvalue(), err.getvalue()


class UntouchableExtractor(FakeEntityExtractor):
    """Stands in for a model that must not load."""

    async def extract(self, text: str) -> list[ExtractedEntityMention]:
        raise AssertionError("the model was used although there was no work")


async def test_no_job_does_not_use_the_model(settings: Settings) -> None:
    assert await run(settings, UntouchableExtractor()) == (
        0,
        "No entity extraction job available.\n",
        "",
    )


async def test_one_job(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await queue_chunks(session_factory, "Merkel met Macron in Berlin.")

    code, out, err = await run(settings, FakeEntityExtractor())

    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0].startswith("Job: ")
    assert lines[1:] == ["Status: completed", "Mentions: 3"]
    async with session_factory() as session:
        assert len(list(await session.scalars(select(EntityMention)))) == 3


async def test_failed_job_exits_with_an_error(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await queue_chunks(session_factory, "Merkel spoke.")
    extractor = FakeEntityExtractor()
    extractor.error = RuntimeError("private details")

    code, out, _ = await run(settings, extractor)

    assert code == 1
    assert "Status: failed\n" in out
    assert "private details" not in out


async def test_loop_stops_after_max_jobs(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await queue_chunks(session_factory, "Merkel one.", "Merkel two.", "Merkel three.")

    code, out, _ = await run(
        settings, FakeEntityExtractor(), once=False, poll_seconds=0.01, max_jobs=2
    )

    assert code == 0
    assert out.count("Status: completed\n") == 2
    assert out.endswith("Jobs handled: 2\n")


class SignallingExtractor(FakeEntityExtractor):
    """Asks the worker to stop while it reads its first chunk."""

    async def extract(self, text: str) -> list[ExtractedEntityMention]:
        if not self.calls:
            signal.raise_signal(signal.SIGINT)
            # Let the event loop see the signal before the job ends.
            for _ in range(100):
                await asyncio.sleep(0)
        return await super().extract(text)


async def test_stop_signal_finishes_the_job_then_stops(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await queue_chunks(session_factory, "Merkel one.", "Merkel two.")

    code, out, _ = await run(
        settings, SignallingExtractor(), once=False, poll_seconds=0.01, max_jobs=5
    )

    assert code == 0
    assert "Stopping after the current job.\n" in out
    assert out.endswith("Jobs handled: 1\n")
