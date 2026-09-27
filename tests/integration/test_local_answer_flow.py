"""From imported files to a citation-checked answer, through the configured Qwen generator.

The Qwen generator is the real class from settings, but a fake stands in for
the Transformers tokenizer and model, so nothing is downloaded. The fake only
names the evidence IDs it is shown. It shows the flow, not answer quality.
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
from fake_qwen import FakeQwen
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
from signalscope.research.local import Qwen3LocalAnswerGenerator
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio

E5 = ("sentence_transformers", "intfloat/multilingual-e5-small")


@pytest.fixture
def providers() -> EmbeddingProviderRegistry:
    registry = EmbeddingProviderRegistry()
    registry.register(FakeEmbeddingProvider(*E5))
    return registry


@pytest.fixture
def qwen() -> FakeQwen:
    return FakeQwen()


@pytest.fixture
async def client(
    migrated_database: Settings, providers: EmbeddingProviderRegistry, qwen: FakeQwen
) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(database_url=migrated_database.database_url, local_answers_enabled=True)
    app = create_app(settings)
    app.state.embedding_providers = providers
    # The generator comes from settings. Only the model loading is replaced.
    generator = app.state.answer_generators.only()
    assert isinstance(generator, Qwen3LocalAnswerGenerator)
    generator.loader = qwen.load
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


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
    sources = {}
    for name in ("Notes", "Reports"):
        response = await client.post("/sources", json={"type": "upload", "name": name})
        assert response.status_code == 201
        sources[name] = uuid.UUID(response.json()["id"])
    notes = await import_and_embed(
        session_factory,
        blobs,
        providers,
        sources["Notes"],
        "Energy notes.txt",
        "text/plain",
        b"Energy prices rose again this winter.",
    )
    report = await import_and_embed(
        session_factory,
        blobs,
        providers,
        sources["Reports"],
        "Harbour Report.pdf",
        "application/pdf",
        make_pdf(["Budget planning for the new year.", "Water flooded the harbour district."]),
    )
    return {"notes": notes, "report": report, "notes_source": sources["Notes"]}


async def answer(client: httpx.AsyncClient, **body: Any) -> httpx.Response:
    return await client.post("/research/answer", json=body)


async def test_answer_cites_only_the_evidence_it_was_shown(
    client: httpx.AsyncClient, library: dict[str, uuid.UUID], qwen: FakeQwen
) -> None:
    response = await answer(client, query="harbour water")

    assert response.status_code == 200, response.text
    result = response.json()
    evidence_ids = [item["evidence_id"] for item in result["evidence"]]
    assert result["answer"]["citation_ids"] == evidence_ids
    assert set(re.findall(r"\[(E\d+)\]", result["answer"]["text"])) == set(evidence_ids)
    first = result["citations"][0]
    assert (first["citation_id"], first["document_id"]) == ("E1", str(library["report"]))
    assert first["title"] == "Harbour Report"
    assert first["chunk_metadata"]["page_number"] == 2
    # The model saw the question and the evidence, and nothing else.
    [[system, user]] = qwen.messages
    assert system["role"] == "system"
    assert user["content"].startswith("Evidence:\n\n[E1]\nTitle: Harbour Report\nText: ")
    assert "Water flooded the harbour district." in user["content"]
    assert user["content"].endswith("\n\nQuestion: harbour water")
    assert str(library["report"]) not in user["content"]
    assert "page_number" not in user["content"]
    assert qwen.generate_options[0]["do_sample"] is False


async def test_source_filter(
    client: httpx.AsyncClient, library: dict[str, uuid.UUID], qwen: FakeQwen
) -> None:
    response = await answer(client, query="energy prices", source_id=str(library["notes_source"]))

    result = response.json()
    assert response.status_code == 200, response.text
    assert {item["document_id"] for item in result["citations"]} == {str(library["notes"])}
    assert "Harbour" not in qwen.messages[0][1]["content"]


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (
            "The harbour flooded [E1].",
            "Answer model transformers/Qwen/Qwen3-4B-Instruct-2507 did not return a JSON answer.",
        ),
        (
            '{"text": "The harbour flooded [E9].", "citation_ids": ["E9"]}',
            "The answer model cited evidence that it was not given: E9.",
        ),
    ],
    ids=["not json", "unknown citation"],
)
async def test_bad_model_output_fails_safely(
    client: httpx.AsyncClient,
    library: dict[str, uuid.UUID],
    qwen: FakeQwen,
    reply: str,
    message: str,
) -> None:
    qwen.reply = reply

    response = await answer(client, query="harbour water")

    assert response.status_code == 503
    assert response.json()["error"]["message"] == message
    assert "harbour flooded" not in response.text
