import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from operations_helpers import LATE, add_content, add_job, user_by_email
from signalscope.core.errors import ConflictError, ForbiddenError, NotFoundError
from signalscope.domain.documents.chunk import DocumentChunk
from signalscope.domain.ingestion.model import IngestionJob, IngestionRun, IngestionStatus
from signalscope.domain.operations.failed_jobs import OperationsJob
from signalscope.domain.operations.queues import QUEUE_TABLES, OperationsQueue
from signalscope.domain.operations.recovery import FailedJobRecoveryService
from signalscope.domain.tenancy.policy import ContentAccessPolicy
from tenancy_helpers import Tenants, add_findings, make_tenants

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)
CHUNK_QUEUES = [
    OperationsQueue.EMBEDDING,
    OperationsQueue.ENTITY_EXTRACTION,
    OperationsQueue.EVENT_EXTRACTION,
    OperationsQueue.CLAIM_EXTRACTION,
]


async def retry(
    session_factory: async_sessionmaker[AsyncSession],
    email: str,
    organization_id: uuid.UUID,
    queue: OperationsQueue,
    job_id: uuid.UUID,
) -> OperationsJob:
    user = await user_by_email(session_factory, email)
    async with session_factory() as session:
        service = FailedJobRecoveryService(
            session, ContentAccessPolicy(session, user), clock=lambda: NOW
        )
        return await service.retry(organization_id, queue, job_id)


async def failed_with_lease(
    session_factory: async_sessionmaker[AsyncSession],
    queue: OperationsQueue,
    content: object,
) -> uuid.UUID:
    job_id = await add_job(
        session_factory,
        queue,
        content,  # type: ignore[arg-type]
        "failed",
        finished_at=LATE,
        last_error="Model failed.",
        attempt_count=2,
    )
    model = QUEUE_TABLES[queue].model
    async with session_factory() as session:
        await session.execute(
            update(model)
            .where(model.id == job_id)
            .values(lease_token=uuid.uuid4(), lease_expires_at=LATE, claimed_at=LATE)
        )
        await session.commit()
    return job_id


async def stored(
    session_factory: async_sessionmaker[AsyncSession], queue: OperationsQueue, job_id: uuid.UUID
) -> object:
    model = QUEUE_TABLES[queue].model
    async with session_factory() as session:
        return await session.get_one(model, job_id)


@pytest.mark.parametrize(
    "queue", [*CHUNK_QUEUES, OperationsQueue.PROCESSING], ids=lambda queue: queue.value
)
async def test_retry_puts_the_job_back(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    queue: OperationsQueue,
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    harbour = await add_content(session_factory, tenants.a.id, "harbour")
    job_id = await failed_with_lease(session_factory, queue, harbour)

    result = await retry(session_factory, "a-admin@example.org", tenants.a.id, queue, job_id)

    assert (result.queue, result.job_id, result.status) == (queue, job_id, "pending")
    assert result.attempt_count == 2
    assert result.available_at == NOW
    assert result.finished_at is None
    assert result.error is None
    job = await stored(session_factory, queue, job_id)
    assert job.lease_token is None  # type: ignore[attr-defined]
    assert job.lease_expires_at is None  # type: ignore[attr-defined]
    assert job.claimed_at is None  # type: ignore[attr-defined]


async def test_ingestion_retry_gets_a_new_run(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    harbour = await add_content(session_factory, tenants.a.id, "harbour")
    job_id = await failed_with_lease(session_factory, OperationsQueue.INGESTION, harbour)
    async with session_factory() as session:
        old_run = (await session.get_one(IngestionJob, job_id)).run_id

    result = await retry(
        session_factory, "system@example.org", tenants.a.id, OperationsQueue.INGESTION, job_id
    )

    assert result.status == "pending"
    async with session_factory() as session:
        job = await session.get_one(IngestionJob, job_id)
        runs = {run.id: run.status for run in (await session.scalars(select(IngestionRun))).all()}
    assert job.run_id != old_run
    assert runs == {old_run: IngestionStatus.FAILED, job.run_id: IngestionStatus.PENDING}

    # A second failed job of the same source cannot start while this one is queued.
    second = await add_job(session_factory, OperationsQueue.INGESTION, harbour, "failed")
    with pytest.raises(ConflictError):
        await retry(
            session_factory, "system@example.org", tenants.a.id, OperationsQueue.INGESTION, second
        )


async def test_refusals(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    harbour = await add_content(session_factory, tenants.a.id, "harbour")
    river = await add_content(session_factory, tenants.b.id, "river")
    queue = OperationsQueue.ENTITY_EXTRACTION
    river_job = await add_job(session_factory, queue, river, "failed")
    running = await add_job(session_factory, queue, harbour, "running", model="m2")

    with pytest.raises(NotFoundError):
        await retry(session_factory, "a-owner@example.org", tenants.a.id, queue, river_job)
    with pytest.raises(NotFoundError):
        # The job exists, but not in the named organization.
        await retry(session_factory, "system@example.org", tenants.a.id, queue, river_job)
    with pytest.raises(NotFoundError):
        await retry(session_factory, "a-owner@example.org", tenants.a.id, queue, uuid.uuid4())
    with pytest.raises(ConflictError):
        await retry(session_factory, "a-owner@example.org", tenants.a.id, queue, running)
    for role in ("member", "viewer"):
        with pytest.raises(ForbiddenError):
            await retry(session_factory, f"a-{role}@example.org", tenants.a.id, queue, running)


async def test_current_results_are_not_redone(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    harbour = await add_content(session_factory, tenants.a.id, "harbour")
    queue = OperationsQueue.ENTITY_EXTRACTION
    # add_findings stores mentions from provider "test", model "m" for the current text.
    await add_findings(session_factory, harbour.chunk_id, claim_text=None)
    job_id = await add_job(session_factory, queue, harbour, "failed")

    with pytest.raises(ConflictError):
        await retry(session_factory, "a-owner@example.org", tenants.a.id, queue, job_id)
    job = await stored(session_factory, queue, job_id)
    assert job.status.value == "failed"  # type: ignore[attr-defined]


async def test_missing_chunk(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    harbour = await add_content(session_factory, tenants.a.id, "harbour")
    queue = OperationsQueue.CLAIM_EXTRACTION
    job_id = await add_job(session_factory, queue, harbour, "failed")
    async with session_factory() as session:
        await session.execute(delete(DocumentChunk).where(DocumentChunk.id == harbour.chunk_id))
        await session.commit()

    with pytest.raises(NotFoundError):
        await retry(session_factory, "a-owner@example.org", tenants.a.id, queue, job_id)
