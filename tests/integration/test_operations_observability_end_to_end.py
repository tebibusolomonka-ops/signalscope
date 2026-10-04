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
from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio

BASE = datetime(2026, 2, 1, 9, 0, tzinfo=UTC)


async def record(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID,
    *,
    queue: OperationAttemptQueue,
    outcome: OperationAttemptOutcome,
    attempt_number: int = 1,
    seconds: float = 4,
) -> None:
    async with session_factory() as session:
        session.add(
            OperationAttempt(
                organization_id=organization_id,
                queue_name=queue,
                job_id=uuid.uuid4(),
                attempt_number=attempt_number,
                resource_type="chunk",
                outcome=outcome,
                started_at=BASE,
                finished_at=BASE + timedelta(seconds=seconds),
                created_at=BASE,
            )
        )
        await session.commit()


async def seed_history(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID
) -> None:
    await record(
        session_factory,
        organization_id,
        queue=OperationAttemptQueue.INGESTION,
        outcome=OperationAttemptOutcome.SUCCEEDED,
    )
    await record(
        session_factory,
        organization_id,
        queue=OperationAttemptQueue.EMBEDDING,
        outcome=OperationAttemptOutcome.FAILED,
    )
    await record(
        session_factory,
        organization_id,
        queue=OperationAttemptQueue.EMBEDDING,
        outcome=OperationAttemptOutcome.RECOVERED,
        attempt_number=2,
        seconds=12,
    )


async def test_operations_observability_is_scoped_to_one_organization(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    await seed_history(session_factory, tenants.a.id)
    await seed_history(session_factory, tenants.b.id)

    trends = await auth_client.get(
        f"/operations/trends?organization_id={tenants.a.id}", headers=tenants.a.headers["owner"]
    )
    history = await auth_client.get(
        f"/operations/history?organization_id={tenants.a.id}", headers=tenants.a.headers["admin"]
    )

    assert trends.status_code == 200
    body = trends.json()
    point = body["points"][0]
    assert point["total"] == 3
    assert point["succeeded"] == 1
    assert point["failed"] == 1
    assert point["recovered"] == 1
    assert point["retried"] == 1
    latency = {item["queue"]: item for item in body["latency"]}
    assert latency["embedding"]["completed"] == 2
    assert latency["embedding"]["max_seconds"] == 12.0

    assert history.status_code == 200
    assert history.json()["total"] == 3

    # Organization B has the same kind of history, but A never sees it.
    for_b = await auth_client.get(
        f"/operations/trends?organization_id={tenants.b.id}", headers=tenants.system
    )
    assert for_b.json()["points"][0]["total"] == 3
    cross = await auth_client.get(
        f"/operations/trends?organization_id={tenants.b.id}", headers=tenants.a.headers["owner"]
    )
    assert cross.status_code == 404
