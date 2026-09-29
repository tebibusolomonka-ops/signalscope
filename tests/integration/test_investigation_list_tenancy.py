import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio


async def create(
    client: httpx.AsyncClient, headers: dict[str, str], organization_id: str, title: str
) -> str:
    response = await client.post(
        "/investigations",
        json={"title": title, "organization_id": organization_id},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    investigation_id: str = response.json()["id"]
    return investigation_id


async def titles(client: httpx.AsyncClient, headers: dict[str, str], query: str = "") -> list[str]:
    response = await client.get(f"/investigations?{query}", headers=headers)
    assert response.status_code == 200, response.text
    return [item["title"] for item in response.json()["items"]]


async def test_list_filters_by_organization(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a, b = tenants.a, tenants.b
    await create(auth_client, a.headers["owner"], str(a.id), "Harbour floods")
    await create(auth_client, b.headers["owner"], str(b.id), "River floods")

    assert await titles(auth_client, tenants.system) == ["River floods", "Harbour floods"]
    assert await titles(auth_client, tenants.system, a.query) == ["Harbour floods"]
    assert await titles(auth_client, tenants.system, b.query) == ["River floods"]
    assert await titles(auth_client, a.headers["admin"], a.query) == ["Harbour floods"]
    # The filter never widens what a user may see.
    assert await titles(auth_client, a.headers["owner"], b.query) == []
    filtered = await auth_client.get(
        f"/investigations?{a.query}&status=closed", headers=a.headers["owner"]
    )
    assert filtered.json()["total"] == 0
