import dataclasses
import hashlib
import io
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.cli import queue_entities
from signalscope.core.settings import Settings
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.entities.job import EntityExtractionJob, EntityExtractionJobStatus
from signalscope.domain.entities.mention import EntityMention
from signalscope.domain.entities.model import Entity
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

GLINER = ("gliner", "urchade/gliner_multi-v2.1")


@pytest.fixture
def settings(database_engine: AsyncEngine, migrated_database: Settings) -> Settings:
    return Settings(database_url=migrated_database.database_url, local_entities_enabled=True)


async def create_chunks(
    session_factory: async_sessionmaker[AsyncSession], count: int
) -> list[DocumentChunk]:
    texts = [f"Merkel in Berlin, part {index} of {uuid.uuid4()}." for index in range(count)]
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
        return await repository.list_by_document(document.id)


async def add_mention(
    session_factory: async_sessionmaker[AsyncSession], chunk: DocumentChunk, text_hash: str
) -> None:
    async with session_factory() as session:
        entity = await session.scalar(select(Entity))
        if entity is None:
            entity = Entity(canonical_name="Merkel", normalized_name="merkel", entity_type="person")
            session.add(entity)
            await session.flush()
        session.add(
            EntityMention(
                entity_id=entity.id,
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                surface_text="Merkel",
                entity_type="person",
                start_char=0,
                end_char=6,
                provider=GLINER[0],
                model=GLINER[1],
                chunk_text_hash=text_hash,
            )
        )
        await session.commit()


async def run(settings: Settings, **options: object) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await queue_entities(settings, out, err, **options)  # type: ignore[arg-type]
    return code, out.getvalue(), err.getvalue()


def counts(checked: int, created: int, extracted: int, queued: int) -> str:
    return (
        f"Chunks checked: {checked}\nJobs created: {created}\n"
        f"Already extracted: {extracted}\nAlready queued: {queued}\n"
    )


async def test_disabled(settings: Settings) -> None:
    code, out, err = await run(dataclasses.replace(settings, local_entities_enabled=False))

    assert (code, out) == (1, "")
    assert err == (
        "Error: Local entity extraction is not enabled. "
        "Set SIGNALSCOPE_LOCAL_ENTITIES_ENABLED=true.\n"
    )


async def test_empty_database(settings: Settings) -> None:
    assert await run(settings) == (0, counts(0, 0, 0, 0), "")


async def test_new_current_stale_and_queued_chunks(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    new, current, stale, queued = await create_chunks(session_factory, 4)
    await add_mention(session_factory, current, current.text_hash)
    await add_mention(session_factory, stale, "0" * 64)
    async with session_factory() as session:
        session.add(
            EntityExtractionJob(
                chunk_id=queued.id,
                provider=GLINER[0],
                model=GLINER[1],
                status=EntityExtractionJobStatus.RUNNING,
            )
        )
        await session.commit()

    code, out, _ = await run(settings)

    assert (code, out) == (0, counts(4, 2, 1, 1))
    async with session_factory() as session:
        jobs = {job.chunk_id: job for job in await session.scalars(select(EntityExtractionJob))}
    assert {new.id, stale.id} <= set(jobs)
    assert current.id not in jobs
    assert {(job.provider, job.model) for job in jobs.values()} == {GLINER}


async def test_document_filter_and_limit(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    mine = await create_chunks(session_factory, 3)
    await create_chunks(session_factory, 2)

    code, out, _ = await run(settings, document_id=mine[0].document_id, limit=2)

    assert (code, out) == (0, counts(2, 2, 0, 0))


async def test_unknown_document(settings: Settings) -> None:
    code, out, err = await run(settings, document_id=uuid.uuid4())

    assert (code, out, err) == (1, "", "Error: Document was not found.\n")
