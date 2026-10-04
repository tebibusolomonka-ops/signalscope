import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio


def report(**overrides):
    base = {
        "report_version": 1,
        "task": "embedding_retrieval",
        "model": "intfloat/multilingual-e5-small",
        "provider": "sentence_transformers",
        "dataset": {"name": "pilot", "fingerprint": "abc123"},
        "created_at": "2026-10-01T00:00:00Z",
        "environment": {"python": "3.12", "hf_token": "secret"},
        "configuration": {},
        "metrics": {"recall@5": 0.8},
        "timings": {"total_seconds": 1.2},
        "warnings": [],
    }
    base.update(overrides)
    return base


async def test_import_list_and_get(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)

    created = await auth_client.post(
        "/admin/evaluations/import", json={"report": report()}, headers=tenants.system
    )
    assert created.status_code == 201, created.text
    report_id = created.json()["id"]
    assert created.json()["report_json"]["metrics"] == {"recall@5": 0.8}
    assert "hf_token" not in created.text

    again = await auth_client.post(
        "/admin/evaluations/import", json={"report": report()}, headers=tenants.system
    )
    assert again.json()["id"] == report_id

    await auth_client.post(
        "/admin/evaluations/import",
        json={"report": report(task="relation_evaluation", metrics={"f1": 0.5})},
        headers=tenants.system,
    )
    listing = await auth_client.get("/admin/evaluations", headers=tenants.system)
    assert listing.json()["total"] == 2
    filtered = await auth_client.get(
        "/admin/evaluations?task=relation_evaluation", headers=tenants.system
    )
    assert [item["task"] for item in filtered.json()["items"]] == ["relation_evaluation"]

    detail = await auth_client.get(f"/admin/evaluations/{report_id}", headers=tenants.system)
    assert detail.json()["dataset_fingerprint"] == "abc123"


async def test_permissions_and_errors(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)

    normal = await auth_client.get("/admin/evaluations", headers=tenants.a.headers["owner"])
    anonymous = await auth_client.get("/admin/evaluations")
    unknown = await auth_client.get(f"/admin/evaluations/{uuid.uuid4()}", headers=tenants.system)
    malformed = await auth_client.post(
        "/admin/evaluations/import", json={"report": {"report_version": 1}}, headers=tenants.system
    )

    assert normal.status_code == 403
    assert anonymous.status_code == 401
    assert unknown.status_code == 404
    assert malformed.status_code == 422


async def test_compare(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)

    async def store(**overrides):
        created = await auth_client.post(
            "/admin/evaluations/import",
            json={"report": report(**overrides)},
            headers=tenants.system,
        )
        return created.json()["id"]

    first = await store(model="e5-small", metrics={"recall@5": 0.8})
    second = await store(model="e5-base", metrics={"recall@5": 0.9})
    other_task = await store(task="relation_evaluation", metrics={"f1": 0.4})

    compared = await auth_client.post(
        "/admin/evaluations/compare",
        json={"report_ids": [first, second]},
        headers=tenants.system,
    )
    assert compared.status_code == 200, compared.text
    body = compared.json()
    assert body["task"] == "embedding_retrieval"
    assert body["reports"] == [first, second]
    assert body["metrics"]["recall@5"]["values"] == [0.8, 0.9]
    assert (
        "winner" not in compared.text
        and "better" not in compared.text
        and "recommend" not in compared.text
    )

    one = await auth_client.post(
        "/admin/evaluations/compare", json={"report_ids": [first]}, headers=tenants.system
    )
    mismatch = await auth_client.post(
        "/admin/evaluations/compare",
        json={"report_ids": [first, other_task]},
        headers=tenants.system,
    )
    unknown = await auth_client.post(
        "/admin/evaluations/compare",
        json={"report_ids": [first, str(uuid.uuid4())]},
        headers=tenants.system,
    )
    denied = await auth_client.post(
        "/admin/evaluations/compare",
        json={"report_ids": [first, second]},
        headers=tenants.a.headers["owner"],
    )
    assert one.status_code == 422
    assert mismatch.status_code == 422
    assert unknown.status_code == 404
    assert denied.status_code == 403
