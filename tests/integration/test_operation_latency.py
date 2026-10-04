import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.operations.attempt import (
    OperationAttempt,
    OperationAttemptOutcome,
    OperationAttemptQueue,
)
from signalscope.domain.operations.latency import OperationLatencyService
from tenancy_helpers import make_tenants

pytestmark = pytest.mark.anyio

BASE = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def completed(
    organization_id: uuid.UUID,
    seconds: float,
    *,
    queue: OperationAttemptQueue = OperationAttemptQueue.INGESTION,
) -> OperationAttempt:
    return OperationAttempt(
        organization_id=organization_id,
        queue_name=queue,
        job_id=uuid.uuid4(),
        attempt_number=1,
        resource_type="source",
        outcome=OperationAttemptOutcome.SUCCEEDED,
        started_at=BASE,
        finished_at=BASE + timedelta(seconds=seconds),
        created_at=BASE,
    )


def running(organization_id: uuid.UUID) -> OperationAttempt:
    return OperationAttempt(
        organization_id=organization_id,
        queue_name=OperationAttemptQueue.INGESTION,
        job_id=uuid.uuid4(),
        attempt_number=1,
        resource_type="source",
        outcome=OperationAttemptOutcome.RUNNING,
        started_at=BASE,
        finished_at=None,
        created_at=BASE,
    )


async def seed(
    session_factory: async_sessionmaker[AsyncSession], *attempts: OperationAttempt
) -> None:
    async with session_factory() as session:
        session.add_all(attempts)
        await session.commit()


async def test_summary_reports_durations_and_percentiles(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    await seed(
        session_factory,
        *[completed(tenants.a.id, seconds) for seconds in (10, 20, 30, 40, 50)],
    )

    async with session_factory() as session:
        report = await OperationLatencyService(session).summarize(tenants.a.id)

    [summary] = report.queues
    assert summary.completed == 5
    assert summary.min_seconds == 10.0
    assert summary.max_seconds == 50.0
    assert summary.average_seconds == 30.0
    assert summary.p50_seconds == 30.0
    assert summary.p95_seconds == 50.0


async def test_single_attempt(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    await seed(session_factory, completed(tenants.a.id, 7))

    async with session_factory() as session:
        report = await OperationLatencyService(session).summarize(tenants.a.id)

    [summary] = report.queues
    assert summary.completed == 1
    assert summary.p50_seconds == 7.0
    assert summary.p95_seconds == 7.0


async def test_running_attempts_are_excluded(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    await seed(session_factory, completed(tenants.a.id, 12), running(tenants.a.id))

    async with session_factory() as session:
        report = await OperationLatencyService(session).summarize(tenants.a.id)

    [summary] = report.queues
    assert summary.completed == 1
    assert summary.max_seconds == 12.0


async def test_empty_and_tenant_isolation(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    await seed(session_factory, completed(tenants.b.id, 99))

    async with session_factory() as session:
        report = await OperationLatencyService(session).summarize(tenants.a.id)

    assert report.queues == ()
