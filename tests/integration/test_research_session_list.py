import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.research.session import ResearchSession
from tenancy_helpers import Tenants, make_tenants

pytestmark = pytest.mark.anyio


async def add_session(
    session_factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID | None,
    title: str,
) -> None:
    async with session_factory() as session:
        session.add(ResearchSession(title=title, organization_id=organization_id))
        await session.commit()


async def titles(client: httpx.AsyncClient, headers: dict[str, str], query: str = "") -> list[str]:
    response = await client.get(f"/research/sessions?{query}", headers=headers)
    assert response.status_code == 200, response.text
    return [item["title"] for item in response.json()["items"]]


async def test_sessions_are_listed_per_organization(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    tenants: Tenants = await make_tenants(auth_client, session_factory)
    a, b = tenants.a, tenants.b
    await add_session(session_factory, a.id, "Harbour first")
    await add_session(session_factory, a.id, "Harbour second")
    await add_session(session_factory, b.id, "River only")
    await add_session(session_factory, None, "Legacy session")

    assert await titles(auth_client, a.headers["viewer"], a.query) == [
        "Harbour second",
        "Harbour first",
    ]
    assert await titles(auth_client, b.headers["member"], b.query) == ["River only"]
    assert await titles(auth_client, tenants.system, a.query) == [
        "Harbour second",
        "Harbour first",
    ]
    assert await titles(auth_client, tenants.system) == ["Legacy session"]
    paged = await auth_client.get(
        f"/research/sessions?{a.query}&limit=1&offset=1", headers=a.headers["owner"]
    )
    assert paged.json()["total"] == 2
    assert [item["title"] for item in paged.json()["items"]] == ["Harbour first"]

    other = await auth_client.get(f"/research/sessions?{a.query}", headers=b.headers["owner"])
    missing = await auth_client.get("/research/sessions", headers=a.headers["owner"])
    anonymous = await auth_client.get(f"/research/sessions?{a.query}")
    assert other.status_code == 404
    assert "Harbour" not in other.text
    assert missing.status_code == 422
    assert anonymous.status_code == 401


async def test_sessions_without_authentication(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_session(session_factory, None, "Open session")

    response = await client.get("/research/sessions")

    assert response.status_code == 200
    assert [item["title"] for item in response.json()["items"]] == ["Open session"]
