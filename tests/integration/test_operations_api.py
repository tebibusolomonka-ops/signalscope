import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from operations_helpers import LATE, add_content, add_job
from signalscope.domain.operations.queues import OperationsQueue
from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio


def overview_path(organization_id: uuid.UUID) -> str:
    return f"/operations/overview?organization_id={organization_id}"


async def test_owner_admin_and_system_admin_see_one_organization(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a, b = tenants.a, tenants.b
    harbour = await add_content(session_factory, a.id, "harbour")
    river = await add_content(session_factory, b.id, "river")
    await add_job(
        session_factory, OperationsQueue.CLAIM_EXTRACTION, harbour, "failed", finished_at=LATE
    )
    await add_job(session_factory, OperationsQueue.INGESTION, harbour, "pending")
    await add_job(session_factory, OperationsQueue.CLAIM_EXTRACTION, river, "running")

    for headers in (a.headers["owner"], a.headers["admin"], tenants.system):
        response = await auth_client.get(overview_path(a.id), headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["organization"] == {"id": str(a.id), "name": "Org a", "slug": "org-a"}
        queues = {item["queue"]: item for item in body["queues"]}
        assert list(queues) == [queue.value for queue in OperationsQueue]
        assert queues["claim_extraction"]["failed_count"] == 1
        assert queues["claim_extraction"]["running_count"] == 0
        assert queues["claim_extraction"]["oldest_failed_at"] == "2026-09-02T08:00:00Z"
        assert queues["ingestion"]["pending_count"] == 1
        assert "river" not in response.text

    by_system = await auth_client.get(overview_path(b.id), headers=tenants.system)
    river_queues = {item["queue"]: item for item in by_system.json()["queues"]}
    assert river_queues["claim_extraction"]["running_count"] == 1
    assert river_queues["claim_extraction"]["failed_count"] == 0


async def test_refused_callers(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a, b = tenants.a, tenants.b

    member = await auth_client.get(overview_path(a.id), headers=a.headers["member"])
    viewer = await auth_client.get(overview_path(a.id), headers=a.headers["viewer"])
    other = await auth_client.get(overview_path(b.id), headers=a.headers["owner"])
    outsider = await auth_client.get(overview_path(a.id), headers=tenants.outsider)
    unknown = await auth_client.get(overview_path(uuid.uuid4()), headers=tenants.system)
    anonymous = await auth_client.get(overview_path(a.id))
    missing = await auth_client.get("/operations/overview", headers=tenants.system)

    assert (member.status_code, viewer.status_code) == (403, 403)
    assert (other.status_code, outsider.status_code, unknown.status_code) == (404, 404, 404)
    assert anonymous.status_code == 401
    assert missing.status_code == 422


async def test_empty_organization_and_no_authentication(
    auth_client: httpx.AsyncClient,
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)

    empty = await auth_client.get(overview_path(tenants.a.id), headers=tenants.a.headers["owner"])
    without_auth = await client.get(overview_path(tenants.a.id))

    assert all(
        item["pending_count"] == item["running_count"] == item["failed_count"] == 0
        for item in empty.json()["queues"]
    )
    assert without_auth.status_code == 503
