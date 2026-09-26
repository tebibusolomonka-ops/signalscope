import io
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sample_files import make_pdf
from signalscope.cli import import_file, run_processing_worker
from signalscope.core.settings import Settings
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import chunk_text
from signalscope.domain.documents.extraction import DocumentExtraction
from signalscope.domain.documents.model import Document
from signalscope.domain.processing.file_import import FileImportService
from signalscope.domain.processing.model import ProcessingJobStatus
from signalscope.domain.processing.processor import DocumentProcessor
from signalscope.domain.processing.worker import DocumentProcessingWorker
from signalscope.parsing.registry import create_default_parser_registry
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio

RESULT_FIELDS = {"document_id", "chunk_id", "source_id", "title", "url", "excerpt", "rank"}


async def create_source(client: httpx.AsyncClient) -> str:
    response = await client.post("/sources", json={"type": "upload", "name": "Files"})
    assert response.status_code == 201
    source_id: str = response.json()["id"]
    return source_id


async def add_document(
    session_factory: async_sessionmaker[AsyncSession],
    source_id: str,
    content: str,
    title: str | None = None,
) -> Document:
    async with session_factory() as session:
        document = Document(source_id=uuid.UUID(source_id), title=title, content=content)
        session.add(document)
        await session.flush()
        await DocumentChunkRepository(session).replace_for_document(
            document.id, chunk_text(content)
        )
        await session.commit()
    return document


async def search(client: httpx.AsyncClient, **params: Any) -> list[dict[str, Any]]:
    response = await client.get("/search", params=params)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def test_matching_results(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source_id = await create_source(client)
    document = await add_document(
        session_factory, source_id, "Climate policy for coastal cities.", title="Coasts"
    )
    await add_document(session_factory, source_id, "Budget report.")

    [item] = await search(client, q="climate policy")

    assert set(item) == RESULT_FIELDS
    assert item["document_id"] == str(document.id)
    assert item["source_id"] == source_id
    assert (item["title"], item["url"]) == ("Coasts", None)
    assert "Climate policy for coastal cities" in item["excerpt"]
    assert item["rank"] > 0
    assert uuid.UUID(item["chunk_id"])


async def test_no_results(client: httpx.AsyncClient) -> None:
    response = await client.get("/search", params={"q": "volcano"})

    assert response.status_code == 200
    assert response.json() == {"items": []}


async def test_ranking(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source_id = await create_source(client)
    filler = " ".join(["other"] * 60)
    weak = await add_document(session_factory, source_id, f"Climate. {filler} Policy.")
    strong = await add_document(session_factory, source_id, "Climate policy. Climate policy.")

    items = await search(client, q="climate policy")

    assert [item["document_id"] for item in items] == [str(strong.id), str(weak.id)]


async def test_source_filter(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    first = await create_source(client)
    second = await create_source(client)
    await add_document(session_factory, first, "Climate report one.")
    in_second = await add_document(session_factory, second, "Climate report two.")

    items = await search(client, q="climate", source_id=second)

    assert [item["document_id"] for item in items] == [str(in_second.id)]


async def test_limit(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    source_id = await create_source(client)
    for number in range(4):
        await add_document(session_factory, source_id, f"Climate report {number}.")

    assert len(await search(client, q="climate", limit=2)) == 2
    assert len(await search(client, q="climate")) == 4


async def test_imported_text_file_is_found_through_the_commands(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    migrated_database: Settings,
    tmp_path: Path,
) -> None:
    settings = Settings(database_url=migrated_database.database_url, blob_dir=tmp_path / "blobs")
    source_id = await create_source(client)
    path = tmp_path / "Harbour notes.txt"
    path.write_bytes(b"The harbour authority published a new flood barrier plan.\n")

    import_code = await import_file(
        uuid.UUID(source_id), path, settings, out=io.StringIO(), err=io.StringIO()
    )
    worker_out = io.StringIO()
    worker_code = await run_processing_worker(settings, worker_out, io.StringIO())

    assert (import_code, worker_code) == (0, 0)
    assert "Status: completed" in worker_out.getvalue()
    [item] = await search(client, q="flood barrier")
    assert item["source_id"] == source_id
    assert item["title"] == "Harbour notes"
    assert "flood barrier plan" in item["excerpt"]


async def test_imported_pdf_goes_through_the_whole_pipeline(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    source_id = await create_source(client)
    blobs = LocalBlobStore(tmp_path / "blobs")
    data = make_pdf(
        ["Quarterly report on wind energy.", "Offshore turbines doubled output."],
        title="Energy Report",
    )

    async with session_factory() as session:
        imported = await FileImportService(session, blobs).import_file(
            uuid.UUID(source_id), filename="energy.pdf", content_type="application/pdf", data=data
        )
    processor = DocumentProcessor(session_factory, blobs, create_default_parser_registry())
    result = await DocumentProcessingWorker(session_factory, processor).run_once()

    assert result.job is not None
    assert result.job.status is ProcessingJobStatus.COMPLETED
    async with session_factory() as session:
        document = await session.get(Document, imported.document.id)
        extraction = await session.scalar(
            select(DocumentExtraction).where(DocumentExtraction.document_id == imported.document.id)
        )
        chunks = await DocumentChunkRepository(session).list_by_document(imported.document.id)
    assert document is not None
    assert document.content == (
        "Quarterly report on wind energy.\n\nOffshore turbines doubled output."
    )
    assert extraction is not None
    assert extraction.parser_name == "PdfDocumentParser"
    assert extraction.parser_metadata["page_count"] == 2
    # One chunk per page, and each knows its page.
    assert [chunk.text for chunk in chunks] == [
        "Quarterly report on wind energy.",
        "Offshore turbines doubled output.",
    ]
    assert [chunk.chunk_metadata["page_number"] for chunk in chunks] == [1, 2]

    [item] = await search(client, q="offshore turbines")
    assert item["document_id"] == str(imported.document.id)
    assert item["chunk_id"] == str(chunks[1].id)
    assert "Offshore turbines doubled output" in item["excerpt"]
