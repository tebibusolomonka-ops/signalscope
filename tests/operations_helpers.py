"""Job rows in every operations queue, for organization operations tests."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.model import Document
from signalscope.domain.ingestion.model import IngestionJob, IngestionRun, IngestionStatus
from signalscope.domain.operations.queues import QUEUE_TABLES, OperationsQueue, ResourceType
from signalscope.domain.users.model import User
from tenancy_helpers import add_document, add_source

EARLY = datetime(2026, 9, 1, 8, tzinfo=UTC)
LATE = datetime(2026, 9, 2, 8, tzinfo=UTC)


@dataclass
class Content:
    """One source, document and chunk of an organization."""

    source_id: uuid.UUID
    document_id: uuid.UUID
    chunk_id: uuid.UUID


async def add_content(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID, tag: str
) -> Content:
    source = await add_source(session_factory, organization_id, f"{tag} feed")
    document, [chunk] = await add_document(session_factory, source, f"{tag}-doc", [f"{tag} text."])
    return Content(source, document, chunk)


async def add_job(
    session_factory: async_sessionmaker[AsyncSession],
    queue: OperationsQueue,
    content: Content,
    status: str,
    *,
    available_at: datetime = EARLY,
    finished_at: datetime | None = None,
    last_error: str | None = None,
    attempt_count: int = 0,
    model: str = "m",
) -> uuid.UUID:
    """One job of the queue for the content, in the given stored status."""
    table = QUEUE_TABLES[queue]
    values = {
        "status": table.status(status),
        "available_at": available_at,
        "finished_at": finished_at,
        "last_error": last_error,
        "attempt_count": attempt_count,
    }
    async with session_factory() as session:
        if table.resource_type is ResourceType.SOURCE:
            run_status = IngestionStatus.FAILED if status == "failed" else IngestionStatus.PENDING
            run = IngestionRun(source_id=content.source_id, status=run_status)
            session.add(run)
            await session.flush()
            job = IngestionJob(source_id=content.source_id, run_id=run.id, **values)
        elif table.resource_type is ResourceType.DOCUMENT:
            # A document has at most one asset, so further processing jobs of
            # the content get their own document in the same source.
            document_id = content.document_id
            if await session.scalar(
                select(DocumentAsset.id).where(DocumentAsset.document_id == document_id)
            ):
                document = Document(source_id=content.source_id, title="Another file")
                session.add(document)
                await session.flush()
                document_id = document.id
            asset = DocumentAsset(
                document_id=document_id,
                storage_key=uuid.uuid4().hex,
                filename="notes.txt",
                content_type="text/plain",
                size_bytes=5,
                sha256="0" * 64,
            )
            session.add(asset)
            await session.flush()
            job = table.model(document_id=document_id, asset_id=asset.id, **values)
        else:
            job = table.model(chunk_id=content.chunk_id, provider="test", model=model, **values)
        session.add(job)
        await session.commit()
        job_id: uuid.UUID = job.id
        return job_id


async def user_by_email(session_factory: async_sessionmaker[AsyncSession], email: str) -> User:
    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == email))
    assert user is not None
    return user
