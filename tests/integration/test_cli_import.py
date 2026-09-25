import io
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.cli import import_file
from signalscope.core.settings import Settings
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.processing.model import DocumentProcessingJob, ProcessingJobStatus
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio


@pytest.fixture
def blob_root(tmp_path: Path) -> Path:
    return tmp_path / "blobs"


@pytest.fixture
def settings(
    database_engine: AsyncEngine, migrated_database: Settings, blob_root: Path
) -> Settings:
    return Settings(database_url=migrated_database.database_url, blob_dir=blob_root)


@pytest.fixture
def text_file(tmp_path: Path) -> Path:
    path = tmp_path / "Climate notes.txt"
    path.write_bytes(b"Climate policy notes.")
    return path


async def create_source(
    session_factory: async_sessionmaker[AsyncSession], source_type: SourceType = SourceType.UPLOAD
) -> Source:
    async with session_factory() as session:
        source = Source(type=source_type, name="Files", url="https://example.com/rss")
        session.add(source)
        await session.commit()
    return source


async def run(
    source_id: uuid.UUID, path: Path, settings: Settings, content_type: str | None = None
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await import_file(source_id, path, settings, content_type, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


async def test_import_queues_the_file(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    text_file: Path,
    blob_root: Path,
) -> None:
    source = await create_source(session_factory)

    code, out, err = await run(source.id, text_file, settings)

    assert (code, err) == (0, "")
    match = re.fullmatch(
        r"Document: ([0-9a-f-]{36})\nAsset: ([0-9a-f-]{36})\nProcessing job: ([0-9a-f-]{36})\n",
        out,
    )
    assert match is not None
    async with session_factory() as session:
        asset = await session.get(DocumentAsset, uuid.UUID(match[2]))
        job = await session.get(DocumentProcessingJob, uuid.UUID(match[3]))
    assert asset is not None
    assert job is not None
    assert str(asset.document_id) == match[1]
    assert asset.content_type == "text/plain"
    assert asset.filename == "Climate notes.txt"
    # The command only queues the file. Nothing is parsed yet.
    assert job.status is ProcessingJobStatus.PENDING
    stored = [path for path in blob_root.rglob("*") if path.is_file()]
    assert [path.read_bytes() for path in stored] == [b"Climate policy notes."]


async def test_content_type_option_wins(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    source = await create_source(session_factory)
    path = tmp_path / "export.data"
    path.write_bytes(b'{"title": "x"}')

    code, out, _ = await run(source.id, path, settings, content_type="application/json")

    assert code == 0
    asset_id = uuid.UUID(out.splitlines()[1].removeprefix("Asset: "))
    async with session_factory() as session:
        asset = await session.get(DocumentAsset, asset_id)
    assert asset is not None
    assert asset.content_type == "application/json"


async def test_wrong_source_type(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    text_file: Path,
    blob_root: Path,
) -> None:
    source = await create_source(session_factory, SourceType.RSS)

    result = await run(source.id, text_file, settings)

    assert result == (
        1,
        "",
        "Error: Files can only be imported into upload sources, not rss sources.\n",
    )
    assert not blob_root.exists() or not any(path.is_file() for path in blob_root.rglob("*"))


async def test_unknown_source(settings: Settings, text_file: Path) -> None:
    assert await run(uuid.uuid4(), text_file, settings) == (
        1,
        "",
        "Error: Source was not found.\n",
    )
