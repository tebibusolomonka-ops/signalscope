import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.asset_service import DocumentAssetService
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.model import Document
from signalscope.domain.processing.processor import DocumentProcessor
from signalscope.domain.search.embedding_job import EmbeddingJob, EmbeddingJobStatus
from signalscope.domain.search.embedding_model import ChunkEmbedding
from signalscope.domain.search.embedding_queue import EmbeddingQueueResult, EmbeddingTarget
from signalscope.domain.sources.model import Source, SourceType
from signalscope.parsing.registry import create_default_parser_registry
from signalscope.storage.local import LocalBlobStore

pytestmark = pytest.mark.anyio

LONG_TEXT = "\n\n".join(
    f"Paragraph {number} about climate policy. " + "Details follow here. " * 20
    for number in range(8)
)
TARGET = EmbeddingTarget(provider="test", model="tiny-3")


@pytest.fixture
def blobs(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(tmp_path / "blobs")


async def store(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore, data: bytes
) -> DocumentAsset:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Files")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, title="Report")
        session.add(document)
        await session.commit()
        return await DocumentAssetService(session, blobs).attach(
            document.id, filename="report.txt", content_type="text/plain", data=data
        )


def processor(
    session_factory: async_sessionmaker[AsyncSession],
    blobs: LocalBlobStore,
    target: EmbeddingTarget | None = TARGET,
) -> DocumentProcessor:
    return DocumentProcessor(
        session_factory, blobs, create_default_parser_registry(), embedding_target=target
    )


async def chunk_ids(
    session_factory: async_sessionmaker[AsyncSession], document_id: uuid.UUID
) -> list[uuid.UUID]:
    async with session_factory() as session:
        chunks = await DocumentChunkRepository(session).list_by_document(document_id)
    return [chunk.id for chunk in chunks]


async def jobs(session_factory: async_sessionmaker[AsyncSession]) -> list[EmbeddingJob]:
    async with session_factory() as session:
        return list(await session.scalars(select(EmbeddingJob)))


async def test_without_a_target_nothing_is_queued(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    asset = await store(session_factory, blobs, LONG_TEXT.encode())

    result = await processor(session_factory, blobs, target=None).process(asset.id)

    assert result.embeddings is None
    assert await chunk_ids(session_factory, asset.document_id) != []
    assert await jobs(session_factory) == []


async def test_new_chunks_are_queued(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    asset = await store(session_factory, blobs, LONG_TEXT.encode())

    result = await processor(session_factory, blobs).process(asset.id)

    ids = await chunk_ids(session_factory, asset.document_id)
    assert len(ids) > 1
    assert result.embeddings == EmbeddingQueueResult(chunks_seen=len(ids), jobs_created=len(ids))
    saved = await jobs(session_factory)
    assert sorted(job.chunk_id for job in saved) == sorted(ids)
    assert {(job.provider, job.model, job.status) for job in saved} == {
        ("test", "tiny-3", EmbeddingJobStatus.PENDING)
    }


async def test_processing_again_replaces_jobs_and_embeddings(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    asset = await store(session_factory, blobs, LONG_TEXT.encode())
    await processor(session_factory, blobs).process(asset.id)
    old_ids = await chunk_ids(session_factory, asset.document_id)
    async with session_factory() as session:
        session.add(
            ChunkEmbedding(
                chunk_id=old_ids[0],
                provider="test",
                model="tiny-3",
                dimensions=3,
                chunk_text_hash="0" * 64,
                embedding=[1.0, 0.0, 0.0],
            )
        )
        await session.commit()

    result = await processor(session_factory, blobs).process(asset.id)

    new_ids = await chunk_ids(session_factory, asset.document_id)
    assert set(new_ids).isdisjoint(old_ids)
    assert result.embeddings == EmbeddingQueueResult(
        chunks_seen=len(new_ids), jobs_created=len(new_ids)
    )
    assert sorted(job.chunk_id for job in await jobs(session_factory)) == sorted(new_ids)
    async with session_factory() as session:
        assert list(await session.scalars(select(ChunkEmbedding))) == []


async def test_queue_failure_rolls_back_the_whole_save(
    session_factory: async_sessionmaker[AsyncSession], blobs: LocalBlobStore
) -> None:
    asset = await store(session_factory, blobs, LONG_TEXT.encode())
    # The provider column holds at most 50 characters, so queueing fails.
    too_long = EmbeddingTarget(provider="p" * 51, model="tiny-3")

    with pytest.raises(DBAPIError):
        await processor(session_factory, blobs, target=too_long).process(asset.id)

    async with session_factory() as session:
        document = await session.get(Document, asset.document_id)
    assert document is not None
    assert document.content is None
    assert await chunk_ids(session_factory, asset.document_id) == []
    assert await jobs(session_factory) == []
