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
