import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from operations_helpers import add_content, add_job, user_by_email
from signalscope.core.errors import ConflictError, ForbiddenError, NotFoundError
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.ingestion.model import IngestionJob, IngestionRun, IngestionStatus
from signalscope.domain.operations.queues import QUEUE_TABLES, OperationsQueue
from signalscope.domain.operations.retry import FailedJobRetryService, RetriedJob
from signalscope.domain.tenancy.policy import ContentAccessPolicy
from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)
FAILED_AT = datetime(2026, 9, 1, tzinfo=UTC)


async def retry(
    session_factory: async_sessionmaker[AsyncSession],
    email: str,
    organization_id: uuid.UUID,
    queue: OperationsQueue,
    job_id: uuid.UUID,
    now: datetime = NOW,
) -> RetriedJob:
    user = await user_by_email(session_factory, email)
    async with session_factory() as session:
        service = FailedJobRetryService(session, ContentAccessPolicy(session, user))
        return await service.retry(organization_id, queue, job_id, now)


async def load_job(
    session_factory: async_sessionmaker[AsyncSession], queue: OperationsQueue, job_id: uuid.UUID
) -> object:
    async with session_factory() as session:
        return await session.get(QUEUE_TABLES[queue].model, job_id)


async def test_retry_requeues_a_failed_chunk_job(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    harbour = await add_content(session_factory, tenants.a.id, "harbour")
    job_id = await add_job(
        session_factory,
        OperationsQueue.CLAIM_EXTRACTION,
        harbour,
        "failed",
        finished_at=FAILED_AT,
        last_error="model failed",
        attempt_count=2,
    )

    result = await retry(
        session_factory,
        "a-owner@example.org",
        tenants.a.id,
        OperationsQueue.CLAIM_EXTRACTION,
        job_id,
    )

    assert result.status == "pending"
    assert result.attempt_count == 2
    assert result.available_at == NOW
    job = await load_job(session_factory, OperationsQueue.CLAIM_EXTRACTION, job_id)
    assert str(job.status) == "pending"
    assert job.available_at == NOW
    assert job.finished_at is None
    assert job.lease_token is None
    assert job.lease_expires_at is None
    assert job.claimed_at is None
    # The attempt count and last error are kept, as when a stale job recovers.
    assert job.attempt_count == 2
    assert job.last_error == "model failed"


async def test_retrying_an_ingestion_job_gives_it_a_fresh_pending_run(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    harbour = await add_content(session_factory, tenants.a.id, "harbour")
    job_id = await add_job(
        session_factory,
        OperationsQueue.INGESTION,
        harbour,
        "failed",
        finished_at=FAILED_AT,
        last_error="fetch failed",
    )
    job = await load_job(session_factory, OperationsQueue.INGESTION, job_id)
    assert isinstance(job, IngestionJob)
    old_run_id = job.run_id

    await retry(
        session_factory, "a-admin@example.org", tenants.a.id, OperationsQueue.INGESTION, job_id
    )

    async with session_factory() as session:
        job = await session.get(IngestionJob, job_id)
        assert job is not None
        assert job.run_id != old_run_id
        new_run = await session.get(IngestionRun, job.run_id)
        old_run = await session.get(IngestionRun, old_run_id)
    assert new_run is not None and new_run.status is IngestionStatus.PENDING
    # The failed run stays in the history.
    assert old_run is not None and old_run.status is IngestionStatus.FAILED


async def test_retry_records_a_safe_audit_event(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    harbour = await add_content(session_factory, tenants.a.id, "harbour")
    job_id = await add_job(
        session_factory,
        OperationsQueue.EMBEDDING,
        harbour,
        "failed",
        finished_at=FAILED_AT,
        last_error="secret failure detail",
        attempt_count=4,
    )
    actor = await user_by_email(session_factory, "a-owner@example.org")

    await retry(
        session_factory, "a-owner@example.org", tenants.a.id, OperationsQueue.EMBEDDING, job_id
    )

    async with session_factory() as session:
        event = await session.scalar(
            select(SecurityAuditEvent).where(SecurityAuditEvent.action == "operations.job_retried")
        )
    assert event is not None
    assert event.action == "operations.job_retried"
    assert event.actor_user_id == actor.id
    assert event.organization_id == tenants.a.id
    assert event.resource_id == job_id
    assert event.details == {"queue": "embedding", "attempt_count": 4}
    # The failure text is never copied into the audit record.
    assert "secret" not in str(event.details)


async def test_a_job_that_is_not_failed_cannot_be_retried(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    harbour = await add_content(session_factory, tenants.a.id, "harbour")
    job_id = await add_job(session_factory, OperationsQueue.EVENT_EXTRACTION, harbour, "pending")

    with pytest.raises(ConflictError):
        await retry(
            session_factory,
            "a-owner@example.org",
            tenants.a.id,
            OperationsQueue.EVENT_EXTRACTION,
            job_id,
        )
    job = await load_job(session_factory, OperationsQueue.EVENT_EXTRACTION, job_id)
    assert str(job.status) == "pending"
    async with session_factory() as session:
        retried = await session.scalar(
            select(SecurityAuditEvent).where(SecurityAuditEvent.action == "operations.job_retried")
        )
    assert retried is None


async def test_retry_permissions_and_tenancy(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    harbour = await add_content(session_factory, tenants.a.id, "harbour")
    job_id = await add_job(
        session_factory, OperationsQueue.EMBEDDING, harbour, "failed", finished_at=FAILED_AT
    )

    for role in ("member", "viewer"):
        with pytest.raises(ForbiddenError):
            await retry(
                session_factory,
                f"a-{role}@example.org",
                tenants.a.id,
                OperationsQueue.EMBEDDING,
                job_id,
            )
    # A job of another organization is not found for that organization's owner.
    with pytest.raises(NotFoundError):
        await retry(
            session_factory, "b-owner@example.org", tenants.b.id, OperationsQueue.EMBEDDING, job_id
        )
    # An unknown job is not found.
    with pytest.raises(NotFoundError):
        await retry(
            session_factory,
            "a-owner@example.org",
            tenants.a.id,
            OperationsQueue.EMBEDDING,
            uuid.uuid4(),
        )
    job = await load_job(session_factory, OperationsQueue.EMBEDDING, job_id)
    assert str(job.status) == "failed"
