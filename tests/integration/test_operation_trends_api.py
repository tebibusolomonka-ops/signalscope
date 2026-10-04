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

BASE = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def trends_path(organization_id: uuid.UUID, extra: str = "") -> str:
    return f"/operations/trends?organization_id={organization_id}{extra}"


async def add_attempt(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID,
    *,
    outcome: OperationAttemptOutcome = OperationAttemptOutcome.SUCCEEDED,
    seconds: float = 5,
    queue: OperationAttemptQueue = OperationAttemptQueue.INGESTION,
) -> None:
    async with session_factory() as session:
        session.add(
            OperationAttempt(
                organization_id=organization_id,
                queue_name=queue,
                job_id=uuid.uuid4(),
                attempt_number=1,
                resource_type="source",
                outcome=outcome,
                started_at=BASE,
                finished_at=BASE + timedelta(seconds=seconds),
                created_at=BASE,
            )
        )
        await session.commit()


async def test_admins_see_trends_and_latency(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    await add_attempt(session_factory, tenants.a.id, outcome=OperationAttemptOutcome.SUCCEEDED)
    await add_attempt(session_factory, tenants.a.id, outcome=OperationAttemptOutcome.FAILED)
    await add_attempt(session_factory, tenants.b.id, outcome=OperationAttemptOutcome.SUCCEEDED)

    response = await auth_client.get(trends_path(tenants.a.id), headers=tenants.a.headers["owner"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["bucket"] == "day"
    assert len(body["points"]) == 1
    assert body["points"][0]["total"] == 2
    assert body["points"][0]["failed"] == 1
    assert body["latency"][0]["completed"] == 2


async def test_queue_filter(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    await add_attempt(session_factory, tenants.a.id, queue=OperationAttemptQueue.INGESTION)
    await add_attempt(session_factory, tenants.a.id, queue=OperationAttemptQueue.EMBEDDING)

    response = await auth_client.get(
        trends_path(tenants.a.id, "&queue=embedding"), headers=tenants.a.headers["admin"]
    )

    assert response.status_code == 200
    assert response.json()["points"][0]["total"] == 1


async def test_refused_callers(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a, b = tenants.a, tenants.b

    member = await auth_client.get(trends_path(a.id), headers=a.headers["member"])
    viewer = await auth_client.get(trends_path(a.id), headers=a.headers["viewer"])
    other = await auth_client.get(trends_path(b.id), headers=a.headers["owner"])
    anonymous = await auth_client.get(trends_path(a.id))
    missing = await auth_client.get("/operations/trends", headers=tenants.system)

    assert (member.status_code, viewer.status_code) == (403, 403)
    assert other.status_code == 404
    assert anonymous.status_code == 401
    assert missing.status_code == 422


async def test_tenant_isolation(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    await add_attempt(session_factory, tenants.b.id, outcome=OperationAttemptOutcome.FAILED)

    response = await auth_client.get(trends_path(tenants.a.id), headers=tenants.system)

    assert response.status_code == 200
    assert response.json()["points"] == []
    assert response.json()["latency"] == []
