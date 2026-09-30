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


def jobs_path(organization_id: uuid.UUID, query: str = "") -> str:
    return f"/operations/jobs?organization_id={organization_id}&{query}"


async def test_failed_jobs_route(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a, b = tenants.a, tenants.b
    harbour = await add_content(session_factory, a.id, "harbour")
    river = await add_content(session_factory, b.id, "river")
    for index in range(3):
        await add_job(
            session_factory,
            OperationsQueue.EMBEDDING,
            harbour,
            "failed",
            finished_at=LATE,
            last_error="Model is not available.",
            model=f"m{index}",
        )
    await add_job(session_factory, OperationsQueue.INGESTION, harbour, "failed", finished_at=LATE)
    await add_job(session_factory, OperationsQueue.INGESTION, river, "failed", last_error="River")

    everything = await auth_client.get(jobs_path(a.id), headers=a.headers["owner"])
    embedding = await auth_client.get(
        jobs_path(a.id, "queue=embedding&limit=2&offset=1"), headers=a.headers["admin"]
    )
    by_system = await auth_client.get(jobs_path(b.id, "status=failed"), headers=tenants.system)

    assert everything.status_code == 200, everything.text
    assert everything.json()["total"] == 4
    assert "River" not in everything.text
    page = embedding.json()
    assert (page["total"], page["limit"], page["offset"], len(page["items"])) == (3, 2, 1, 2)
    item = page["items"][0]
    assert item["queue"] == "embedding"
    assert item["resource_type"] == "chunk"
    assert item["resource_id"] == str(harbour.chunk_id)
    assert item["error"] == "Model is not available."
    assert set(item) == {
        "queue",
        "job_id",
        "status",
        "resource_type",
        "resource_id",
        "provider",
        "model",
        "attempt_count",
        "available_at",
        "created_at",
        "finished_at",
        "error",
    }
    assert [job["error"] for job in by_system.json()["items"]] == ["River"]

    member = await auth_client.get(jobs_path(a.id), headers=a.headers["member"])
    viewer = await auth_client.get(jobs_path(a.id), headers=a.headers["viewer"])
    other = await auth_client.get(jobs_path(b.id), headers=a.headers["owner"])
    unknown_queue = await auth_client.get(
        jobs_path(a.id, "queue=blob_cleanup"), headers=a.headers["owner"]
    )
    assert (member.status_code, viewer.status_code) == (403, 403)
    assert other.status_code == 404
    assert unknown_queue.status_code == 422


def retry_path(organization_id: uuid.UUID) -> str:
    return f"/operations/jobs/retry?organization_id={organization_id}"


async def test_retry_route_requeues_a_failed_job(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a = tenants.a
    harbour = await add_content(session_factory, a.id, "harbour")
    job_id = await add_job(
        session_factory,
        OperationsQueue.EMBEDDING,
        harbour,
        "failed",
        finished_at=LATE,
        last_error="Model is not available.",
        attempt_count=1,
    )

    body = {"queue": "embedding", "job_id": str(job_id)}
    response = await auth_client.post(retry_path(a.id), json=body, headers=a.headers["admin"])

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["job_id"] == str(job_id)
    assert payload["queue"] == "embedding"
    assert payload["attempt_count"] == 1
    assert set(payload) == {
        "queue",
        "job_id",
        "status",
        "resource_type",
        "resource_id",
        "attempt_count",
        "available_at",
    }
    # The job now appears as pending, not failed.
    listed = await auth_client.get(jobs_path(a.id), headers=a.headers["owner"])
    assert listed.json()["total"] == 0


async def test_retry_route_refused_callers_and_states(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a, b = tenants.a, tenants.b
    harbour = await add_content(session_factory, a.id, "harbour")
    failed_id = await add_job(
        session_factory, OperationsQueue.EMBEDDING, harbour, "failed", finished_at=LATE, model="a"
    )
    pending_id = await add_job(
        session_factory, OperationsQueue.EMBEDDING, harbour, "pending", model="b"
    )

    def body(job_id: uuid.UUID) -> dict[str, str]:
        return {"queue": "embedding", "job_id": str(job_id)}

    member = await auth_client.post(
        retry_path(a.id), json=body(failed_id), headers=a.headers["member"]
    )
    viewer = await auth_client.post(
        retry_path(a.id), json=body(failed_id), headers=a.headers["viewer"]
    )
    other = await auth_client.post(
        retry_path(b.id), json=body(failed_id), headers=b.headers["owner"]
    )
    anonymous = await auth_client.post(retry_path(a.id), json=body(failed_id))
    still_pending = await auth_client.post(
        retry_path(a.id), json=body(pending_id), headers=a.headers["owner"]
    )
    unknown = await auth_client.post(
        retry_path(a.id), json=body(uuid.uuid4()), headers=a.headers["owner"]
    )

    assert (member.status_code, viewer.status_code) == (403, 403)
    assert other.status_code == 404
    assert anonymous.status_code == 401
    assert still_pending.status_code == 409
    assert unknown.status_code == 404
