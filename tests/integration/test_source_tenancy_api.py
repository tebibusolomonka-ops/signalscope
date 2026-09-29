import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tenancy_helpers import ROLES, Tenants, add_source, make_tenants

pytestmark = pytest.mark.anyio

FEED = {"type": "rss", "name": "Harbour feed", "url": "https://example.org/feed.xml"}
SCHEDULE = {"interval_minutes": 60}


@pytest.fixture
async def tenants(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> Tenants:
    return await make_tenants(auth_client, session_factory)


async def test_create_and_list(auth_client: httpx.AsyncClient, tenants: Tenants) -> None:
    a, b = tenants.a, tenants.b
    created = {}
    for tenant in (a, b):
        # The same feed can be configured by both organizations.
        response = await auth_client.post(
            "/sources",
            json=FEED | {"organization_id": str(tenant.id)},
            headers=tenant.headers["admin"],
        )
        assert response.status_code == 201, response.text
        created[tenant.id] = response.json()
    assert created[a.id]["organization_id"] == str(a.id)

    listed = {
        role: await auth_client.get(f"/sources?{a.query}", headers=a.headers[role])
        for role in ROLES
    }
    for response in listed.values():
        assert [item["id"] for item in response.json()["items"]] == [created[a.id]["id"]]
        assert created[b.id]["id"] not in response.text
    other = await auth_client.get(f"/sources?{b.query}", headers=a.headers["owner"])
    missing = await auth_client.get("/sources", headers=a.headers["owner"])
    assert (other.status_code, missing.status_code) == (404, 422)


async def test_create_needs_manage(auth_client: httpx.AsyncClient, tenants: Tenants) -> None:
    a = tenants.a
    body = FEED | {"organization_id": str(a.id)}

    statuses = {
        role: (await auth_client.post("/sources", json=body, headers=a.headers[role])).status_code
        for role in ROLES
    }
    without_organization = await auth_client.post("/sources", json=FEED, headers=tenants.system)
    other = await auth_client.post("/sources", json=body, headers=tenants.b.headers["owner"])

    assert statuses == {"owner": 201, "admin": 201, "member": 403, "viewer": 403}
    # No new legacy sources through the API, not even for system admins.
    assert without_organization.status_code == 422
    assert other.status_code == 404


async def test_read_and_manage_one_source(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    tenants: Tenants,
) -> None:
    a = tenants.a
    source_id = await add_source(session_factory, a.id)
    path = f"/sources/{source_id}"

    for role in ROLES:
        assert (await auth_client.get(path, headers=a.headers[role])).status_code == 200
    manage = {
        role: (
            await auth_client.put(f"{path}/schedule", json=SCHEDULE, headers=a.headers[role])
        ).status_code
        for role in ROLES
    }
    unschedule = await auth_client.delete(f"{path}/schedule", headers=a.headers["viewer"])
    run = await auth_client.post(
        "/ingestion-runs", json={"source_id": str(source_id)}, headers=a.headers["member"]
    )
    delete = await auth_client.delete(path, headers=a.headers["member"])

    assert manage == {"owner": 200, "admin": 200, "member": 403, "viewer": 403}
    assert (unschedule.status_code, run.status_code, delete.status_code) == (403, 403, 403)
    started = await auth_client.post(
        "/ingestion-runs", json={"source_id": str(source_id)}, headers=a.headers["admin"]
    )
    assert started.status_code == 201
    run_path = f"/ingestion-runs/{started.json()['id']}"
    assert (await auth_client.get(run_path, headers=a.headers["viewer"])).status_code == 200
    runs = await auth_client.get(f"/ingestion-runs?{a.query}", headers=a.headers["viewer"])
    assert [item["id"] for item in runs.json()["items"]] == [started.json()["id"]]
    assert (await auth_client.delete(path, headers=a.headers["owner"])).status_code == 409


async def test_other_organizations_and_legacy(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    tenants: Tenants,
) -> None:
    a, b = tenants.a, tenants.b
    b_source = await add_source(session_factory, b.id, "B only feed")
    legacy = await add_source(session_factory, None, "Legacy feed")
    b_path = f"/sources/{b_source}"

    for method, path, body in [
        ("GET", b_path, None),
        ("PUT", f"{b_path}/schedule", SCHEDULE),
        ("DELETE", b_path, None),
        ("POST", "/ingestion-runs", {"source_id": str(b_source)}),
        ("GET", f"/ingestion-runs?source_id={b_source}&{a.query}", None),
        ("GET", f"/sources/{legacy}", None),
    ]:
        response = await auth_client.request(method, path, json=body, headers=a.headers["owner"])
        assert response.status_code == 404, (method, path)
        assert "B only feed" not in response.text

    legacy_list = await auth_client.get("/sources", headers=tenants.system)
    assert [item["id"] for item in legacy_list.json()["items"]] == [str(legacy)]
    assert (await auth_client.get(f"/sources/{legacy}", headers=tenants.system)).status_code == 200
    by_system = await auth_client.get(f"/sources?{b.query}", headers=tenants.system)
    assert [item["id"] for item in by_system.json()["items"]] == [str(b_source)]
    assert (await auth_client.get(b_path, headers=tenants.outsider)).status_code == 404


async def test_auth_disabled_keeps_global_sources(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    created = await client.post("/sources", json=FEED)
    owned = await add_source(session_factory, None)
    with_organization = await client.post(
        "/sources", json=FEED | {"organization_id": "00000000-0000-0000-0000-000000000001"}
    )

    assert created.status_code == 201
    assert created.json()["organization_id"] is None
    assert (await client.get("/sources")).json()["total"] == 2
    assert (await client.get(f"/sources/{owned}")).status_code == 200
    assert with_organization.status_code == 422
