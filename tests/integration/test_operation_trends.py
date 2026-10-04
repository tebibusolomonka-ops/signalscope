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
from signalscope.domain.operations.trends import OperationTrendService, TrendBucket
from tenancy_helpers import make_tenants

pytestmark = pytest.mark.anyio

DAY1 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
DAY2 = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)


def attempt(
    organization_id: uuid.UUID,
    *,
    outcome: OperationAttemptOutcome,
    created_at: datetime,
    queue: OperationAttemptQueue = OperationAttemptQueue.INGESTION,
    attempt_number: int = 1,
) -> OperationAttempt:
    return OperationAttempt(
        organization_id=organization_id,
        queue_name=queue,
        job_id=uuid.uuid4(),
        attempt_number=attempt_number,
        resource_type="source",
        outcome=outcome,
        created_at=created_at,
    )


async def seed(
    session_factory: async_sessionmaker[AsyncSession], *attempts: OperationAttempt
) -> None:
    async with session_factory() as session:
        session.add_all(attempts)
        await session.commit()


async def test_day_buckets_count_outcomes_and_retries(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    await seed(
        session_factory,
        attempt(tenants.a.id, outcome=OperationAttemptOutcome.SUCCEEDED, created_at=DAY1),
        attempt(
            tenants.a.id,
            outcome=OperationAttemptOutcome.FAILED,
            created_at=DAY1 + timedelta(hours=2),
        ),
        attempt(
            tenants.a.id,
            outcome=OperationAttemptOutcome.RECOVERED,
            created_at=DAY2,
            attempt_number=2,
        ),
    )

    async with session_factory() as session:
        report = await OperationTrendService(session).summarize(
            tenants.a.id, bucket=TrendBucket.DAY
        )

    assert [point.bucket_start.date() for point in report.points] == [DAY1.date(), DAY2.date()]
    assert report.points[0].total == 2
    assert report.points[0].succeeded == 1
    assert report.points[0].failed == 1
    assert report.points[1].recovered == 1
    assert report.points[1].retried == 1


async def test_hour_bucket_splits_within_a_day(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    await seed(
        session_factory,
        attempt(tenants.a.id, outcome=OperationAttemptOutcome.SUCCEEDED, created_at=DAY1),
        attempt(
            tenants.a.id,
            outcome=OperationAttemptOutcome.SUCCEEDED,
            created_at=DAY1 + timedelta(hours=1),
        ),
    )

    async with session_factory() as session:
        report = await OperationTrendService(session).summarize(
            tenants.a.id, bucket=TrendBucket.HOUR
        )

    assert len(report.points) == 2
    assert all(point.total == 1 for point in report.points)


async def test_queue_and_range_filters(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    await seed(
        session_factory,
        attempt(
            tenants.a.id,
            outcome=OperationAttemptOutcome.SUCCEEDED,
            created_at=DAY1,
            queue=OperationAttemptQueue.INGESTION,
        ),
        attempt(
            tenants.a.id,
            outcome=OperationAttemptOutcome.SUCCEEDED,
            created_at=DAY1,
            queue=OperationAttemptQueue.EMBEDDING,
        ),
        attempt(tenants.a.id, outcome=OperationAttemptOutcome.SUCCEEDED, created_at=DAY2),
    )

    async with session_factory() as session:
        service = OperationTrendService(session)
        embedding = await service.summarize(tenants.a.id, queue="embedding")
        ranged = await service.summarize(tenants.a.id, start=DAY1, end=DAY1 + timedelta(days=1))

    assert sum(point.total for point in embedding.points) == 1
    assert sum(point.total for point in ranged.points) == 2


async def test_isolated_by_organization_and_empty_range(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants = await make_tenants(auth_client, session_factory)
    await seed(
        session_factory,
        attempt(tenants.a.id, outcome=OperationAttemptOutcome.SUCCEEDED, created_at=DAY1),
        attempt(tenants.b.id, outcome=OperationAttemptOutcome.FAILED, created_at=DAY1),
    )

    async with session_factory() as session:
        service = OperationTrendService(session)
        for_a = await service.summarize(tenants.a.id)
        empty = await service.summarize(tenants.a.id, start=DAY2, end=DAY2 + timedelta(days=1))

    assert sum(point.total for point in for_a.points) == 1
    assert for_a.points[0].failed == 0  # B's failure must not appear
    assert empty.points == ()
