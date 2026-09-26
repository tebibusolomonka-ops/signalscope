"""The whole vector search flow, from an imported file to search results.

The embedding model is a fake that counts a few words. It only makes the
expected order of results easy to work out.
"""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fake_embeddings import FakeEmbeddingProvider
from sample_files import make_pdf
from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.core.settings import Settings
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.processing.file_import import FileImportService
from signalscope.domain.processing.model import ProcessingJobStatus
from signalscope.domain.processing.processor import DocumentProcessor
from signalscope.domain.processing.worker import DocumentProcessingWorker
from signalscope.domain.search.embedding_coverage import (
    EmbeddingCoverage,
    EmbeddingCoverageService,
)
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.search.embedding_queue import EmbeddingQueueService, EmbeddingTarget
from signalscope.domain.search.embedding_worker import EmbeddingWorker
from signalscope.embeddings.registry import EmbeddingProviderRegistry
from signalscope.parsing.registry import create_default_parser_registry
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio


@pytest.fixture
def words() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
def energy_only() -> FakeEmbeddingProvider:
    # A second model that only looks at one word, so its order differs.
    return FakeEmbeddingProvider(model_name="energy-2", words=["energy"])


@pytest.fixture
def providers(
    words: FakeEmbeddingProvider, energy_only: FakeEmbeddingProvider
) -> EmbeddingProviderRegistry:
    registry = EmbeddingProviderRegistry()
    registry.register(words)
    registry.register(energy_only)
    return registry


@pytest.fixture
async def client(
    migrated_database: Settings, providers: EmbeddingProviderRegistry
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(migrated_database)
    app.state.embedding_providers = providers
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
def blobs(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(tmp_path / "blobs")


async def create_source(client: httpx.AsyncClient) -> uuid.UUID:
    response = await client.post("/sources", json={"type": "upload", "name": "Files"})
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


async def import_and_process(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    source_id: uuid.UUID,
    filename: str,
    content_type: str,
    data: bytes,
    target: EmbeddingTarget,
) -> uuid.UUID:
    """Import a file and process it, which queues embedding jobs for its chunks."""
    async with session_factory() as session:
        imported = await FileImportService(session, blobs).import_file(
            source_id, filename=filename, content_type=content_type, data=data
        )
    processor = DocumentProcessor(
        session_factory, blobs, create_default_parser_registry(), embedding_target=target
    )
    result = await DocumentProcessingWorker(session_factory, processor).run_once()
    assert result.job is not None and result.job.status is ProcessingJobStatus.COMPLETED
    return imported.document.id


async def run_embedding_worker(
    session_factory: async_sessionmaker[AsyncSession], providers: EmbeddingProviderRegistry
) -> int:
    worker = EmbeddingWorker(session_factory, providers)
    done = 0
    while (result := await worker.run_once()).jobs:
        assert result.lease_lost == 0
        done += len(result.jobs)
    return done


async def embedding_count(session_factory: async_sessionmaker[AsyncSession], model: str) -> int:
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(ChunkEmbedding).where(ChunkEmbedding.model == model)
        )
    return count or 0


async def get_items(client: httpx.AsyncClient, path: str, **params: Any) -> list[dict[str, Any]]:
    response = await client.get(path, params={"provider": "test", **params})
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def test_imported_text_is_found_by_semantic_and_hybrid_search(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    providers: EmbeddingProviderRegistry,
    words: FakeEmbeddingProvider,
) -> None:
    source_id = await create_source(client)
    target = EmbeddingTarget(words.provider_name, words.model_name)
    water_id = await import_and_process(
        session_factory,
        blobs,
        source_id,
        "Reservoir.txt",
        "text/plain",
        b"Water levels in the reservoir fell. Water use must drop.",
        target,
    )
    await import_and_process(
        session_factory,
        blobs,
        source_id,
        "Grid.txt",
        "text/plain",
        b"Energy demand on the grid keeps rising.",
        target,
    )

    assert await run_embedding_worker(session_factory, providers) == 2
    assert await embedding_count(session_factory, words.model_name) == 2
    coverage = await EmbeddingCoverageService(session_factory).for_document(
        water_id, words.provider_name, words.model_name
    )
    assert coverage == EmbeddingCoverage(
        chunk_count=1, embedded_count=1, pending_count=0, failed_count=0
    )

    semantic = await get_items(client, "/search/semantic", q="water", model="words-4")
    assert [item["document_id"] for item in semantic][0] == str(water_id)
    assert semantic[0]["title"] == "Reservoir"

    hybrid = await get_items(client, "/search/hybrid", q="reservoir water", model="words-4")
    assert hybrid[0]["document_id"] == str(water_id)
    assert hybrid[0]["lexical_rank"] == 1
    assert hybrid[0]["vector_similarity"] is not None
    assert "reservoir" in hybrid[0]["excerpt"]


async def test_several_documents_come_back_in_the_expected_order(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    providers: EmbeddingProviderRegistry,
    words: FakeEmbeddingProvider,
) -> None:
    source_id = await create_source(client)
    target = EmbeddingTarget(words.provider_name, words.model_name)
    texts = {
        "mostly_water": "Water water water and some energy.",
        "only_energy": "Energy energy energy.",
        "mixed": "Water and energy in equal parts.",
    }
    ids = {
        name: await import_and_process(
            session_factory,
            blobs,
            source_id,
            f"{name}.txt",
            "text/plain",
            text.encode(),
            target,
        )
        for name, text in texts.items()
    }
    await run_embedding_worker(session_factory, providers)

    semantic = await get_items(client, "/search/semantic", q="water", model="words-4")

    assert [item["document_id"] for item in semantic] == [
        str(ids["mostly_water"]),
        str(ids["mixed"]),
        str(ids["only_energy"]),
    ]
    similarities = [item["similarity"] for item in semantic]
    assert similarities == sorted(similarities, reverse=True)


async def test_models_are_kept_apart(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    providers: EmbeddingProviderRegistry,
    words: FakeEmbeddingProvider,
    energy_only: FakeEmbeddingProvider,
) -> None:
    source_id = await create_source(client)
    water_id = await import_and_process(
        session_factory,
        blobs,
        source_id,
        "water.txt",
        "text/plain",
        b"Water supply.",
        EmbeddingTarget(words.provider_name, words.model_name),
    )
    await run_embedding_worker(session_factory, providers)

    # The second model has no embeddings yet, so it finds nothing.
    assert await get_items(client, "/search/semantic", q="energy", model="energy-2") == []
    assert await embedding_count(session_factory, "energy-2") == 0

    await EmbeddingQueueService(session_factory).queue_document(
        water_id, energy_only.provider_name, energy_only.model_name
    )
    await run_embedding_worker(session_factory, providers)

    [item] = await get_items(client, "/search/semantic", q="energy", model="energy-2")
    assert item["document_id"] == str(water_id)
    assert await embedding_count(session_factory, "energy-2") == 1
    assert await embedding_count(session_factory, "words-4") == 1


async def test_pdf_pages_are_kept_in_the_results(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    providers: EmbeddingProviderRegistry,
    words: FakeEmbeddingProvider,
) -> None:
    source_id = await create_source(client)
    data = make_pdf(
        ["Climate goals for the city.", "Energy use of public buildings.", "Water in the parks."],
        title="City Plan",
    )
    document_id = await import_and_process(
        session_factory,
        blobs,
        source_id,
        "plan.pdf",
        "application/pdf",
        data,
        EmbeddingTarget(words.provider_name, words.model_name),
    )

    assert await run_embedding_worker(session_factory, providers) == 3
    async with session_factory() as session:
        pages = list(
            await session.scalars(
                select(DocumentChunk.chunk_metadata)
                .where(DocumentChunk.document_id == document_id)
                .order_by(DocumentChunk.position)
            )
        )
    assert [page["page_number"] for page in pages] == [1, 2, 3]

    semantic = await get_items(client, "/search/semantic", q="energy", model="words-4")
    assert semantic[0]["chunk_metadata"]["page_number"] == 2
    hybrid = await get_items(client, "/search/hybrid", q="parks water", model="words-4")
    assert hybrid[0]["chunk_metadata"]["page_number"] == 3
    assert hybrid[0]["lexical_rank"] == 1
