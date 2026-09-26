"""From imported files to a citation-checked answer, with fake models.

The fake answer model only restates titles. It shows how answers and
citations flow, not answer quality.
"""

import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_answers import FakeAnswerGenerator
from fake_embeddings import FakeEmbeddingProvider
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
from signalscope.research.generation import GeneratedAnswer
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio

E5 = ("sentence_transformers", "intfloat/multilingual-e5-small")


@pytest.fixture
def providers() -> EmbeddingProviderRegistry:
    registry = EmbeddingProviderRegistry()
    registry.register(FakeEmbeddingProvider(*E5))
    return registry


@pytest.fixture
def generator() -> FakeAnswerGenerator:
    return FakeAnswerGenerator()


@pytest.fixture
async def client(
    migrated_database: Settings,
    providers: EmbeddingProviderRegistry,
    generator: FakeAnswerGenerator,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(migrated_database)
    app.state.embedding_providers = providers
    app.state.answer_generators.register(generator)
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


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


@pytest.fixture
async def library(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    providers: EmbeddingProviderRegistry,
) -> dict[str, uuid.UUID]:
    """A text file in one source and a two-page PDF in another."""
    blobs = LocalBlobStore(tmp_path / "blobs")
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
        "Harbour Report.pdf",
        "application/pdf",
        make_pdf(["Budget planning for the new year.", "Water flooded the harbour district."]),
    )
    return {"notes": notes, "report": report, "notes_source": notes_source}


async def answer(client: httpx.AsyncClient, **body: Any) -> httpx.Response:
    return await client.post("/research/answer", json=body)


async def test_answer_cites_the_evidence_it_was_given(
    client: httpx.AsyncClient, library: dict[str, uuid.UUID], generator: FakeAnswerGenerator
) -> None:
    response = await answer(client, query="harbour water")

    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["query"], result["mode"]) == ("harbour water", "hybrid")
    evidence_ids = [item["evidence_id"] for item in result["evidence"]]
    cited = result["answer"]["citation_ids"]
    assert cited == evidence_ids
    assert set(re.findall(r"\[(E\d+)\]", result["answer"]["text"])) == set(cited)
    # Every citation says which document, chunk and page it is.
    assert [item["citation_id"] for item in result["citations"]] == cited
    first = result["citations"][0]
    assert first["document_id"] == str(library["report"])
    assert first["chunk_id"] == result["evidence"][0]["chunk_id"]
    assert first["title"] == "Harbour Report"
    assert first["chunk_metadata"]["page_number"] == 2
    # The model was given the same evidence, as structured items and as text.
    [request] = generator.requests
    assert [item.evidence_id for item in request.evidence] == evidence_ids
    assert request.context_text.startswith("[E1]\nTitle: Harbour Report\nPage: 2\n")


async def test_source_filter(client: httpx.AsyncClient, library: dict[str, uuid.UUID]) -> None:
    response = await answer(client, query="energy prices", source_id=str(library["notes_source"]))

    result = response.json()
    assert {item["document_id"] for item in result["citations"]} == {str(library["notes"])}


async def test_bad_citation_is_never_returned(
    client: httpx.AsyncClient, library: dict[str, uuid.UUID], generator: FakeAnswerGenerator
) -> None:
    generator.answer = GeneratedAnswer(text="The harbour flooded [E9].", citation_ids=("E9",))

    response = await answer(client, query="harbour water")

    assert response.status_code == 503
    message = response.json()["error"]["message"]
    assert message == "The answer model cited evidence that it was not given: E9."
    assert "harbour flooded" not in message


async def test_model_crash_gives_a_safe_error(
    client: httpx.AsyncClient, library: dict[str, uuid.UUID], generator: FakeAnswerGenerator
) -> None:
    generator.error = RuntimeError("private details")

    response = await answer(client, query="harbour water")

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Answer generation failed."


async def test_no_evidence_means_no_answer(
    client: httpx.AsyncClient, library: dict[str, uuid.UUID], generator: FakeAnswerGenerator
) -> None:
    response = await answer(client, query="volcano", mode="lexical")

    assert response.status_code == 200
    assert response.json() == {
        "query": "volcano",
        "mode": "lexical",
        "answer": None,
        "citations": [],
        "evidence": [],
    }
    assert generator.requests == []
