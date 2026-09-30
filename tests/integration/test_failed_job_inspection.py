import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from operations_helpers import add_content, add_job, user_by_email
from signalscope.core.errors import ForbiddenError, NotFoundError
from signalscope.domain.operations.failed_jobs import FailedJob, FailedJobInspectionService
from signalscope.domain.operations.queues import OperationsQueue, ResourceType
from signalscope.domain.tenancy.policy import ContentAccessPolicy
from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio

START = datetime(2026, 9, 1, tzinfo=UTC)


async def failed(
    session_factory: async_sessionmaker[AsyncSession],
    email: str,
    organization_id: uuid.UUID,
    queue: OperationsQueue | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[FailedJob], int]:
    user = await user_by_email(session_factory, email)
    async with session_factory() as session:
        service = FailedJobInspectionService(session, ContentAccessPolicy(session, user))
        return await service.list_page(organization_id, queue, limit, offset)


async def test_failed_jobs_of_every_queue_newest_first(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    harbour = await add_content(session_factory, tenants.a.id, "harbour")
    river = await add_content(session_factory, tenants.b.id, "river")
    expected = []
    for index, queue in enumerate(OperationsQueue):
        job_id = await add_job(
            session_factory,
            queue,
            harbour,
            "failed",
            finished_at=START + timedelta(hours=index),
            last_error=f"{queue.value} failed",
            attempt_count=3,
        )
        expected.append((queue, job_id))
        await add_job(session_factory, queue, harbour, "pending", model="other")
        await add_job(
            session_factory, queue, river, "failed", finished_at=START, last_error="river failed"
        )

    jobs, total = await failed(session_factory, "a-owner@example.org", tenants.a.id)

    assert total == len(OperationsQueue)
    assert [(job.queue, job.job_id) for job in jobs] == list(reversed(expected))
    by_queue = {job.queue: job for job in jobs}
    assert by_queue[OperationsQueue.INGESTION].resource_type is ResourceType.SOURCE
    assert by_queue[OperationsQueue.INGESTION].resource_id == harbour.source_id
    assert by_queue[OperationsQueue.PROCESSING].resource_id == harbour.document_id
    entity_job = by_queue[OperationsQueue.ENTITY_EXTRACTION]
    assert (entity_job.resource_type, entity_job.resource_id) == (
        ResourceType.CHUNK,
        harbour.chunk_id,
    )
    assert (entity_job.provider, entity_job.model) == ("test", "m")
    assert by_queue[OperationsQueue.PROCESSING].provider is None
    assert all(job.status == "failed" and job.attempt_count == 3 for job in jobs)
    assert by_queue[OperationsQueue.EMBEDDING].error == "embedding failed"
    assert all(job.error != "river failed" for job in jobs)


async def test_queue_filter_and_paging(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    harbour = await add_content(session_factory, tenants.a.id, "harbour")
    ids = [
        await add_job(
            session_factory,
            OperationsQueue.CLAIM_EXTRACTION,
            harbour,
            "failed",
            finished_at=START + timedelta(minutes=index),
            model=f"m{index}",
        )
        for index in range(5)
    ]
    await add_job(session_factory, OperationsQueue.EVENT_EXTRACTION, harbour, "failed")

    claims, total = await failed(
        session_factory,
        "a-admin@example.org",
        tenants.a.id,
        OperationsQueue.CLAIM_EXTRACTION,
        limit=2,
        offset=1,
    )
    everything, all_total = await failed(session_factory, "system@example.org", tenants.a.id)

    assert total == 5
    assert [job.job_id for job in claims] == [ids[3], ids[2]]
    assert all_total == 6
    # A failed job without a finish time comes last.
    assert everything[-1].queue is OperationsQueue.EVENT_EXTRACTION


async def test_permissions(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)

    for role in ("member", "viewer"):
        with pytest.raises(ForbiddenError):
            await failed(session_factory, f"a-{role}@example.org", tenants.a.id)
    with pytest.raises(NotFoundError):
        await failed(session_factory, "a-owner@example.org", tenants.b.id)
