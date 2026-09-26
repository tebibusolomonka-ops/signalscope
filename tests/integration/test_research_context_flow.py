"""From imported files to research context, with fake models.

The fakes stand in for the local E5 and mMARCO models under their names, so
the endpoint finds them. Their scores only count words and mean nothing.
"""

import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_embeddings import FakeEmbeddingProvider
from fake_reranker import FakeReranker
from sample_files import make_pdf
from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.core.settings import Settings
from signalscope.domain.processing.file_import import FileImportService
from signalscope.domain.processing.model import ProcessingJobStatus
from signalscope.domain.processing.processor import DocumentProcessor
from signalscope.domain.processing.worker import DocumentProcessingWorker
from signalscope.domain.search.embedding_queue import EmbeddingTarget
from signalscope.domain.search.embedding_worker import EmbeddingWorker
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.parsing.registry import create_default_parser_registry
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio

E5 = ("sentence_transformers", "intfloat/multilingual-e5-small")
MMARCO = ("sentence_transformers", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")


@pytest.fixture
def providers() -> EmbeddingProviderRegistry:
    registry = EmbeddingProviderRegistry()
    registry.register(FakeEmbeddingProvider(*E5))
    return registry


@pytest.fixture
async def client(
    migrated_database: Settings, providers: EmbeddingProviderRegistry
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(migrated_database)
    app.state.embedding_providers = providers
    app.state.rerankers.register(FakeReranker(*MMARCO))
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
def blobs(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(tmp_path / "blobs")


async def create_source(client: httpx.AsyncClient, name: str) -> uuid.UUID:
    response = await client.post("/sources", json={"type": "upload", "name": name})
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


async def import_and_embed(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    providers: EmbeddingProviderRegistry,
    source_id: uuid.UUID,
    filename: str,
    content_type: str,
    data: bytes,
) -> uuid.UUID:
    async with session_factory() as session:
        imported = await FileImportService(session, blobs).import_file(
            source_id, filename=filename, content_type=content_type, data=data
        )
    processor = DocumentProcessor(
        session_factory,
        blobs,
        create_default_parser_registry(),
        embedding_target=EmbeddingTarget(*E5),
    )
    result = await DocumentProcessingWorker(session_factory, processor).run_once()
    assert result.job is not None and result.job.status is ProcessingJobStatus.COMPLETED
    worker = EmbeddingWorker(session_factory, providers)
    while (await worker.run_once()).jobs:
        pass
    return imported.document.id


async def research(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    response = await client.post("/research/context", json=body)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


@pytest.fixture
async def library(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    providers: EmbeddingProviderRegistry,
) -> dict[str, uuid.UUID]:
    """A text file in one source and a two-page PDF in another."""
    notes_source = await create_source(client, "Notes")
    reports_source = await create_source(client, "Reports")
    notes = await import_and_embed(
        session_factory,
        blobs,
        providers,
        notes_source,
        "Energy notes.txt",
        "text/plain",
        b"Energy prices rose again this winter.",
    )
    report = await import_and_embed(
        session_factory,
        blobs,
        providers,
        reports_source,
        # Imported files take their title from the file name.
        "Harbour Report.pdf",
        "application/pdf",
        make_pdf(
            ["Budget planning for the new year.", "Water flooded the harbour district."],
            title="Harbour Report",
        ),
    )
    return {
        "notes": notes,
        "report": report,
        "notes_source": notes_source,
        "reports_source": reports_source,
    }


async def test_evidence_and_context_match(
    client: httpx.AsyncClient, library: dict[str, uuid.UUID]
) -> None:
    result = await research(client, query="harbour water")

    assert (result["query"], result["mode"]) == ("harbour water", "hybrid")
    first = result["evidence"][0]
    assert first["evidence_id"] == "E1"
    assert first["document_id"] == str(library["report"])
    # The PDF page survives from parsing, through chunking and search, into evidence.
    assert first["chunk_metadata"]["page_number"] == 2
    assert "text" not in first

    # Every evidence ID has exactly one block in the context, in the same order.
    ids = [item["evidence_id"] for item in result["evidence"]]
    assert re.findall(r"^\[(E\d+)\]$", result["context_text"], flags=re.MULTILINE) == ids
    first_block = result["context_text"].split("\n\n")[0]
    assert first_block.splitlines() == [
        "[E1]",
        "Title: Harbour Report",
        "Page: 2",
        "Text: Water flooded the harbour district.",
    ]


async def test_source_filter(client: httpx.AsyncClient, library: dict[str, uuid.UUID]) -> None:
    result = await research(client, query="energy prices", source_id=str(library["notes_source"]))

    assert {item["document_id"] for item in result["evidence"]} == {str(library["notes"])}
    assert result["context_text"].startswith("[E1]\nTitle: Energy notes\n")


async def test_lexical_and_reranked_modes(
    client: httpx.AsyncClient, library: dict[str, uuid.UUID]
) -> None:
    lexical = await research(client, query="harbour", mode="lexical", limit=3)
    reranked = await research(client, query="water harbour", mode="reranked", limit=3)

    assert [item["chunk_metadata"]["page_number"] for item in lexical["evidence"]] == [2]
    assert set(lexical["evidence"][0]["scores"]) == {"rank"}
    assert reranked["evidence"][0]["document_id"] == str(library["report"])
    assert reranked["evidence"][0]["scores"]["reranker_score"] == 2.0


async def test_nothing_found(client: httpx.AsyncClient, library: dict[str, uuid.UUID]) -> None:
    result = await research(client, query="volcano", mode="lexical")

    assert (result["evidence"], result["context_text"]) == ([], "")
