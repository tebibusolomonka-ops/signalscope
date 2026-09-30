import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from operations_helpers import EARLY, LATE, add_content, add_job, user_by_email
from signalscope.core.errors import ForbiddenError, NotFoundError
from signalscope.domain.operations.overview import OperationsOverview, OrganizationOperationsService
from signalscope.domain.operations.queues import OperationsQueue
from signalscope.domain.tenancy.policy import ContentAccessPolicy
from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio


async def overview(
    session_factory: async_sessionmaker[AsyncSession], email: str, organization_id: uuid.UUID
) -> OperationsOverview:
    user = await user_by_email(session_factory, email)
    async with session_factory() as session:
        service = OrganizationOperationsService(session, ContentAccessPolicy(session, user))
        return await service.overview(organization_id)


def counts(result: OperationsOverview) -> dict[str, tuple[int, int, int]]:
    return {
        item.queue.value: (item.pending_count, item.running_count, item.failed_count)
        for item in result.queues
    }


async def test_empty_organization(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)

    result = await overview(session_factory, "a-owner@example.org", tenants.a.id)

    assert result.organization.id == tenants.a.id
    assert [item.queue for item in result.queues] == list(OperationsQueue)
    assert set(counts(result).values()) == {(0, 0, 0)}
    assert all(item.oldest_pending_at is None for item in result.queues)
    assert all(item.oldest_failed_at is None for item in result.queues)


async def test_counts_every_queue_for_one_organization(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a = await add_content(session_factory, tenants.a.id, "harbour")
    b = await add_content(session_factory, tenants.b.id, "river")
    for queue in OperationsQueue:
        await add_job(session_factory, queue, a, "pending", available_at=LATE, model="m1")
        await add_job(session_factory, queue, a, "pending", available_at=EARLY, model="m2")
        await add_job(session_factory, queue, a, "running", model="m3")
        await add_job(session_factory, queue, a, "failed", finished_at=LATE, model="m4")
        await add_job(session_factory, queue, a, "completed", finished_at=EARLY, model="m5")
        await add_job(session_factory, queue, b, "failed", finished_at=EARLY, model="m1")

    result = await overview(session_factory, "a-admin@example.org", tenants.a.id)

    assert set(counts(result).values()) == {(2, 1, 1)}
    for item in result.queues:
        assert item.oldest_pending_at == EARLY
        assert item.oldest_failed_at == LATE
    other = await overview(session_factory, "b-owner@example.org", tenants.b.id)
    assert set(counts(other).values()) == {(0, 0, 1)}


async def test_access(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    b = await add_content(session_factory, tenants.b.id, "river")
    await add_job(session_factory, OperationsQueue.EMBEDDING, b, "failed", finished_at=LATE)

    for role in ("member", "viewer"):
        with pytest.raises(ForbiddenError):
            await overview(session_factory, f"a-{role}@example.org", tenants.a.id)
    with pytest.raises(NotFoundError):
        await overview(session_factory, "a-owner@example.org", tenants.b.id)
    with pytest.raises(NotFoundError):
        await overview(session_factory, "outsider@example.org", tenants.a.id)

    as_system_a = await overview(session_factory, "system@example.org", tenants.a.id)
    as_system_b = await overview(session_factory, "system@example.org", tenants.b.id)
    assert counts(as_system_a)["embedding"] == (0, 0, 0)
    assert counts(as_system_b)["embedding"] == (0, 0, 1)
