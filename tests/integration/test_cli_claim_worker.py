import asyncio
import hashlib
import io
import signal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fake_claims import FakeClaimExtractor
from signalscope.claims.provider import ExtractedClaim
from signalscope.claims.registry import ClaimExtractorRegistry
from signalscope.cli import run_claim_worker
from signalscope.core.settings import Settings
from signalscope.domain.claims.model import ClaimEvidence
from signalscope.domain.claims.queue import ClaimExtractionQueueService
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.model import Source, SourceType

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
    await ClaimExtractionQueueService(session_factory).queue_chunks(
        [chunk.id for chunk in saved], "test", "number-sentences"
    )


async def run(
    settings: Settings, extractor: FakeClaimExtractor, **options: Any
) -> tuple[int, str, str]:
    registry = ClaimExtractorRegistry()
    registry.register(extractor)
    out, err = io.StringIO(), io.StringIO()
    code = await asyncio.wait_for(
        run_claim_worker(settings, out, err, extractors=registry, **options), TIMEOUT_SECONDS
    )
    return code, out.getvalue(), err.getvalue()


class UntouchableExtractor(FakeClaimExtractor):
    """Stands in for a model that must not load."""

    async def extract(self, text: str) -> list[ExtractedClaim]:
        raise AssertionError("the model was used although there was no work")


async def test_no_job_does_not_use_the_model(settings: Settings) -> None:
    assert await run(settings, UntouchableExtractor()) == (
        0,
        "No claim extraction job available.\n",
        "",
    )


async def test_one_job(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await queue_chunks(session_factory, "Prices rose 5%. Wages rose 3%.")

    code, out, err = await run(settings, FakeClaimExtractor())

    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0].startswith("Job: ")
    assert lines[1:] == ["Status: completed", "Claims: 2"]
    async with session_factory() as session:
        assert len(list(await session.scalars(select(ClaimEvidence)))) == 2


async def test_failed_job_exits_with_an_error(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await queue_chunks(session_factory, "Prices rose 5%.")
    extractor = FakeClaimExtractor()
    extractor.error = RuntimeError("private details")

    code, out, _ = await run(settings, extractor)

    assert code == 1
    assert "Status: failed\n" in out
    assert "private details" not in out


async def test_loop_stops_after_max_jobs(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await queue_chunks(session_factory, "Rose 1%.", "Rose 2%.", "Rose 3%.")

    code, out, _ = await run(
        settings, FakeClaimExtractor(), once=False, poll_seconds=0.01, max_jobs=2
    )

    assert code == 0
    assert out.count("Status: completed\n") == 2
    assert out.endswith("Jobs handled: 2\n")


class SignallingExtractor(FakeClaimExtractor):
    """Asks the worker to stop while it reads its first chunk."""

    async def extract(self, text: str) -> list[ExtractedClaim]:
        if not self.calls:
            signal.raise_signal(signal.SIGINT)
            # Let the event loop see the signal before the job ends.
            for _ in range(100):
                await asyncio.sleep(0)
        return await super().extract(text)


async def test_stop_signal_finishes_the_job_then_stops(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await queue_chunks(session_factory, "Rose 1%.", "Rose 2%.")

    code, out, _ = await run(
        settings, SignallingExtractor(), once=False, poll_seconds=0.01, max_jobs=5
    )

    assert code == 0
    assert "Stopping after the current job.\n" in out
    assert out.endswith("Jobs handled: 1\n")
