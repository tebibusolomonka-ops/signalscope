import dataclasses
import io
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.cli import import_file, run_processing_worker
from signalscope.core.settings import Settings
from signalscope.domain.documents.model import Document
from signalscope.domain.search.embedding_job import EmbeddingJob
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio


@pytest.fixture
def settings(database_engine: AsyncEngine, migrated_database: Settings, tmp_path: Path) -> Settings:
    return Settings(database_url=migrated_database.database_url, blob_dir=tmp_path / "blobs")


@pytest.fixture
async def source(session_factory: async_sessionmaker[AsyncSession]) -> Source:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.commit()
    return source


async def import_local_file(
    settings: Settings, source: Source, path: Path, content_type: str | None = None
) -> None:
    code = await import_file(
        source.id, path, settings, content_type, out=io.StringIO(), err=io.StringIO()
    )
    assert code == 0


async def run(settings: Settings) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await run_processing_worker(settings, out, err)
    return code, out.getvalue(), err.getvalue()


async def test_no_work(settings: Settings) -> None:
    assert await run(settings) == (0, "No document processing job available.\n", "")


async def test_processes_an_imported_file(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    tmp_path: Path,
) -> None:
    path = tmp_path / "notes.txt"
    path.write_bytes(b"Climate policy notes.")
    await import_local_file(settings, source, path)

    code, out, err = await run(settings)

    assert (code, err) == (0, "")
    match = re.fullmatch(r"Job: [0-9a-f-]{36}\nStatus: completed\nDocument: ([0-9a-f-]{36})\n", out)
    assert match is not None
    async with session_factory() as session:
        document = await session.get(Document, uuid.UUID(match[1]))
    assert document is not None
    assert document.content == "Climate policy notes."
    assert (await run(settings))[1] == "No document processing job available.\n"


async def test_failed_processing_exits_with_an_error(
    settings: Settings, source: Source, tmp_path: Path
) -> None:
    path = tmp_path / "picture.png"
    path.write_bytes(b"\x89PNG data")
    await import_local_file(settings, source, path, content_type="image/png")

    code, out, _ = await run(settings)

    assert code == 1
    assert out.splitlines()[1] == "Status: failed"
    assert out.splitlines()[3] == "Error: No parser is available for image/png."


async def test_enabled_local_embeddings_queue_jobs_for_new_chunks(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    tmp_path: Path,
) -> None:
    path = tmp_path / "notes.txt"
    path.write_bytes(b"Climate policy notes.")
    await import_local_file(settings, source, path)
    enabled = dataclasses.replace(settings, local_embeddings_enabled=True)

    code, _, _ = await run(enabled)

    assert code == 0
    async with session_factory() as session:
        jobs = list(await session.scalars(select(EmbeddingJob)))
    assert [(job.provider, job.model) for job in jobs] == [
        ("sentence_transformers", "intfloat/multilingual-e5-small")
    ]


async def test_disabled_local_embeddings_queue_nothing(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    source: Source,
    tmp_path: Path,
) -> None:
    path = tmp_path / "notes.txt"
    path.write_bytes(b"Climate policy notes.")
    await import_local_file(settings, source, path)

    assert (await run(settings))[0] == 0

    async with session_factory() as session:
        assert list(await session.scalars(select(EmbeddingJob))) == []
