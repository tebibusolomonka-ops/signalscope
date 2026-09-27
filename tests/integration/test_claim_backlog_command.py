import dataclasses
import hashlib
import io
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.cli import queue_claims
from signalscope.core.settings import Settings
from signalscope.domain.claims.job import ClaimExtractionJob, ClaimExtractionJobStatus
from signalscope.domain.claims.model import Claim, ClaimEvidence
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.documents.chunk_repository import DocumentChunkRepository
from signalscope.domain.documents.chunking import TextChunk
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio

GLINER2 = ("gliner2", "fastino/gliner2.5-multi-v1")


@pytest.fixture
def settings(database_engine: AsyncEngine, migrated_database: Settings) -> Settings:
    return Settings(database_url=migrated_database.database_url, local_structured_enabled=True)


async def create_chunks(
    session_factory: async_sessionmaker[AsyncSession], count: int
) -> list[DocumentChunk]:
    texts = [f"Prices rose 5%, part {index} of {uuid.uuid4()}." for index in range(count)]
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
        source = Source(type=SourceType.UPLOAD, name=f"Files {uuid.uuid4()}")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id)
        session.add(document)
        await session.flush()
        repository = DocumentChunkRepository(session)
        await repository.replace_for_document(document.id, chunks)
        await session.commit()
        return await repository.list_by_document(document.id)


async def run(settings: Settings, **options: object) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await queue_claims(settings, out, err, **options)  # type: ignore[arg-type]
    return code, out.getvalue(), err.getvalue()


def counts(checked: int, created: int, extracted: int, queued: int) -> str:
    return (
        f"Chunks checked: {checked}\nJobs created: {created}\n"
        f"Already extracted: {extracted}\nAlready queued: {queued}\n"
    )


async def test_disabled(settings: Settings) -> None:
    code, out, err = await run(dataclasses.replace(settings, local_structured_enabled=False))

    assert (code, out) == (1, "")
    assert err == (
        "Error: Local structured extraction is not enabled. "
        "Set SIGNALSCOPE_LOCAL_STRUCTURED_ENABLED=true.\n"
    )


async def test_empty_database(settings: Settings) -> None:
    assert await run(settings) == (0, counts(0, 0, 0, 0), "")


async def test_new_extracted_and_queued_chunks(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    new, with_claims, completed, queued = await create_chunks(session_factory, 4)
    async with session_factory() as session:
        claim = Claim(
            text="Prices rose 5%", normalized_text="prices rose 5%", claim_type="statistic"
        )
        session.add(claim)
        await session.flush()
        session.add(
            ClaimEvidence(
                claim_id=claim.id,
                chunk_id=with_claims.id,
                surface_text="Prices",
                start_char=0,
                end_char=6,
                provider=GLINER2[0],
                model=GLINER2[1],
            )
        )
        session.add_all(
            [
                ClaimExtractionJob(
                    chunk_id=completed.id,
                    provider=GLINER2[0],
                    model=GLINER2[1],
                    status=ClaimExtractionJobStatus.COMPLETED,
                ),
                ClaimExtractionJob(
                    chunk_id=queued.id,
                    provider=GLINER2[0],
                    model=GLINER2[1],
                    status=ClaimExtractionJobStatus.RUNNING,
                ),
            ]
        )
        await session.commit()

    code, out, _ = await run(settings)

    assert (code, out) == (0, counts(4, 1, 2, 1))
    async with session_factory() as session:
        jobs = {job.chunk_id: job for job in await session.scalars(select(ClaimExtractionJob))}
    assert jobs[new.id].status is ClaimExtractionJobStatus.PENDING
    assert with_claims.id not in jobs
    assert {(job.provider, job.model) for job in jobs.values()} == {GLINER2}

    # Running it again finds nothing new.
    assert (await run(settings))[1] == counts(4, 0, 2, 2)


async def test_document_filter_and_limit(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    mine = await create_chunks(session_factory, 3)
    await create_chunks(session_factory, 2)

    code, out, _ = await run(settings, document_id=mine[0].document_id, limit=2)

    assert (code, out) == (0, counts(2, 2, 0, 0))
    async with session_factory() as session:
        chunk_ids = set(await session.scalars(select(ClaimExtractionJob.chunk_id)))
    assert chunk_ids == {mine[0].id, mine[1].id}


async def test_unknown_document(settings: Settings) -> None:
    code, out, err = await run(settings, document_id=uuid.uuid4())

    assert (code, out, err) == (1, "", "Error: Document was not found.\n")
