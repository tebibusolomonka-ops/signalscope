import asyncio
import hashlib
import io
import signal
from collections.abc import Sequence
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fake_embeddings import FakeEmbeddingProvider
from signalscope.cli import run_embedding_worker
from signalscope.core.settings import Settings
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.search.embedding_queue import EmbeddingQueueService
from signalscope.domain.sources.model import Source, SourceType
from signalscope.embeddings.provider import EmbeddingInputRole
from signalscope.embeddings.registry import EmbeddingProviderRegistry

pytestmark = pytest.mark.anyio

TIMEOUT_SECONDS = 10


@pytest.fixture
def settings(database_engine: AsyncEngine, migrated_database: Settings) -> Settings:
    return Settings(database_url=migrated_database.database_url)


async def queue_chunks(
    session_factory: async_sessionmaker[AsyncSession],
    provider: FakeEmbeddingProvider,
    *texts: str,
) -> None:
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
        await DocumentChunkRepository(session).replace_for_document(document.id, chunks)
        await session.commit()
    await EmbeddingQueueService(session_factory).queue_document(
        document.id, provider.provider_name, provider.model_name
    )


async def run(
    settings: Settings, provider: FakeEmbeddingProvider, **options: Any
) -> tuple[int, str, str]:
    registry = EmbeddingProviderRegistry()
    registry.register(provider)
    out, err = io.StringIO(), io.StringIO()
    code = await asyncio.wait_for(
        run_embedding_worker(settings, out, err, providers=registry, **options),
        TIMEOUT_SECONDS,
    )
    return code, out.getvalue(), err.getvalue()


async def test_no_work(settings: Settings) -> None:
    assert await run(settings, FakeEmbeddingProvider()) == (
        0,
        "No embedding job available.\n",
        "",
    )


async def test_one_batch(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    provider = FakeEmbeddingProvider()
    await queue_chunks(session_factory, provider, "Water.", "Energy.", "Climate.")

    code, out, err = await run(settings, provider)

    assert (code, err) == (0, "")
    assert out == "Model: test/words-4\nJobs: 3\nCompleted: 3\nFailed: 0\nLease lost: 0\n"
    assert len(provider.calls) == 1
    async with session_factory() as session:
        assert len(list(await session.scalars(select(ChunkEmbedding)))) == 3


async def test_failed_batch_exits_with_an_error(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    provider = FakeEmbeddingProvider()
    provider.error = RuntimeError("private details")
    await queue_chunks(session_factory, provider, "Water.")

    code, out, _ = await run(settings, provider)

    assert code == 1
    assert "Failed: 1\n" in out
    assert "private details" not in out


async def test_loop_stops_after_max_jobs(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    provider = FakeEmbeddingProvider()
    await queue_chunks(session_factory, provider, "One.", "Two.", "Three.")

    code, out, _ = await run(
        settings, provider, once=False, poll_seconds=0.01, max_jobs=2, batch_size=1
    )

    assert code == 0
    assert out.count("Jobs: 1\n") == 2
    assert out.endswith("Jobs handled: 2\n")
    assert [len(call) for call in provider.calls] == [1, 1]


class SignallingProvider(FakeEmbeddingProvider):
    """Asks the worker to stop while it embeds its first batch."""

    async def embed_texts(
        self, texts: Sequence[str], role: EmbeddingInputRole
    ) -> list[list[float]]:
        if not self.calls:
            signal.raise_signal(signal.SIGINT)
            # Let the event loop see the signal before the batch ends.
            for _ in range(100):
                await asyncio.sleep(0)
        return await super().embed_texts(texts, role)


async def test_stop_signal_finishes_the_batch_then_stops(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    provider = SignallingProvider()
    await queue_chunks(session_factory, provider, "One.", "Two.")

    code, out, _ = await run(
        settings, provider, once=False, poll_seconds=0.01, max_jobs=5, batch_size=1
    )

    assert code == 0
    assert "Stopping after the current job.\n" in out
    assert out.endswith("Jobs handled: 1\n")
    assert "Completed: 1\n" in out
