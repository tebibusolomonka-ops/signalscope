import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.model import Document
from signalscope.domain.processing.model import DocumentProcessingJob, ProcessingJobStatus
from signalscope.domain.sources.model import Source, SourceType

pytestmark = pytest.mark.anyio


async def create_asset(session_factory: async_sessionmaker[AsyncSession]) -> DocumentAsset:
    async with session_factory() as session:
        source = Source(type=SourceType.UPLOAD, name="Uploads")
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id)
        session.add(document)
        await session.flush()
        asset = DocumentAsset(
            document_id=document.id,
            storage_key=f"ab/{uuid.uuid4().hex}",
            content_type="text/plain",
            size_bytes=5,
            sha256=hashlib.sha256(b"hello").hexdigest(),
        )
        session.add(asset)
        await session.commit()
    return asset


async def add_job(
    session_factory: async_sessionmaker[AsyncSession], asset: DocumentAsset
) -> DocumentProcessingJob:
    async with session_factory() as session:
        job = DocumentProcessingJob(document_id=asset.document_id, asset_id=asset.id)
        session.add(job)
        await session.commit()
    return job


async def test_new_job_defaults(session_factory: async_sessionmaker[AsyncSession]) -> None:
    asset = await create_asset(session_factory)
    before = datetime.now(UTC)

    job = await add_job(session_factory, asset)

    async with session_factory() as session:
        saved = await session.get(DocumentProcessingJob, job.id)
    assert saved is not None
    assert saved.status is ProcessingJobStatus.PENDING
    assert saved.attempt_count == 0
    assert (saved.claimed_at, saved.finished_at, saved.last_error) == (None, None, None)
    # The database clock can differ a little from the test clock.
    assert abs((saved.available_at - before).total_seconds()) < 60


async def test_database_defaults(session_factory: async_sessionmaker[AsyncSession]) -> None:
    asset = await create_asset(session_factory)

    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "INSERT INTO document_processing_jobs (id, document_id, asset_id, status) "
                    "VALUES (:id, :document_id, :asset_id, 'pending') "
                    "RETURNING attempt_count, available_at IS NOT NULL"
                ),
                {"id": uuid.uuid4(), "document_id": asset.document_id, "asset_id": asset.id},
            )
        ).one()

    assert tuple(row) == (0, True)


async def test_an_asset_cannot_have_two_jobs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    asset = await create_asset(session_factory)
    await add_job(session_factory, asset)

    async with session_factory() as session:
        session.add(DocumentProcessingJob(document_id=asset.document_id, asset_id=asset.id))
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.parametrize(
    "values",
    [
        {"attempt_count": -1},
        {"status": "waiting"},
        {"asset_id": uuid.uuid4()},
        {"document_id": uuid.uuid4()},
    ],
)
async def test_invalid_job_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], values: dict[str, Any]
) -> None:
    asset = await create_asset(session_factory)
    row = {
        "id": uuid.uuid4(),
        "document_id": asset.document_id,
        "asset_id": asset.id,
        "status": "pending",
        "attempt_count": 0,
    } | values

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO document_processing_jobs "
                    "(id, document_id, asset_id, status, attempt_count) "
                    "VALUES (:id, :document_id, :asset_id, :status, :attempt_count)"
                ),
                row,
            )


async def test_asset_with_a_job_cannot_be_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    asset = await create_asset(session_factory)
    await add_job(session_factory, asset)

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(delete(DocumentAsset).where(DocumentAsset.id == asset.id))


async def test_foreign_keys(database_engine: AsyncEngine) -> None:
    async with database_engine.connect() as connection:
        foreign_keys = await connection.run_sync(
            lambda sync: inspect(sync).get_foreign_keys("document_processing_jobs")
        )

    referred = {key["constrained_columns"][0]: key["referred_table"] for key in foreign_keys}
    assert referred == {"document_id": "documents", "asset_id": "document_assets"}
    assert all(key["options"]["ondelete"] == "RESTRICT" for key in foreign_keys)


async def test_indexes(database_engine: AsyncEngine) -> None:
    async with database_engine.connect() as connection:
        indexes = await connection.run_sync(
            lambda sync: inspect(sync).get_indexes("document_processing_jobs")
        )

    columns = {index["name"]: index["column_names"] for index in indexes}
    assert columns["ix_document_processing_jobs_status_available_at"] == [
        "status",
        "available_at",
    ]
    assert columns["ix_document_processing_jobs_document_id"] == ["document_id"]


async def test_status_is_stored_as_its_value(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    asset = await create_asset(session_factory)
    job = await add_job(session_factory, asset)

    async with session_factory() as session:
        status = await session.scalar(
            text("SELECT status FROM document_processing_jobs WHERE id = :id"), {"id": job.id}
        )

    assert status == "pending"
