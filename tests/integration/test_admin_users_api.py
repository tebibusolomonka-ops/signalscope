import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from password_helpers import OTHER_PASSWORD, TEST_PASSWORD
from signalscope.domain.users.credential import UserPasswordCredential

pytestmark = pytest.mark.anyio


@pytest.fixture
async def headers(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> dict[str, dict[str, str]]:
    await create_account(session_factory, "root@example.org", system_admin=True)
    await create_account(session_factory, "ana@example.org", display_name="Ana Silva")
    return {
        "root": bearer(await login(auth_client, "root@example.org")),
        "ana": bearer(await login(auth_client, "ana@example.org")),
    }


async def test_list_filter_and_search(
    auth_client: httpx.AsyncClient, headers: dict[str, dict[str, str]]
) -> None:
    root = headers["root"]

    everyone = (await auth_client.get("/admin/users", headers=root)).json()
    admins = (await auth_client.get("/admin/users?is_system_admin=true", headers=root)).json()
    searched = (await auth_client.get("/admin/users?query=silva", headers=root)).json()
    inactive = (await auth_client.get("/admin/users?is_active=false", headers=root)).json()
    paged = (await auth_client.get("/admin/users?limit=1&offset=1", headers=root)).json()

    assert [user["email"] for user in everyone["items"]] == ["root@example.org", "ana@example.org"]
    assert set(everyone["items"][0]) == {
        "id",
        "email",
        "display_name",
        "is_active",
        "is_system_admin",
        "created_at",
        "updated_at",
    }
    assert [user["email"] for user in admins["items"]] == ["root@example.org"]
    assert [user["email"] for user in searched["items"]] == ["ana@example.org"]
    assert inactive == {"items": [], "total": 0, "limit": 50, "offset": 0}
    assert (paged["total"], [user["email"] for user in paged["items"]]) == (
        2,
        ["ana@example.org"],
    )


async def test_create_and_get(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    headers: dict[str, dict[str, str]],
) -> None:
    body = {"email": "cleo@example.org", "display_name": "Cleo", "password": OTHER_PASSWORD}

    created = await auth_client.post("/admin/users", json=body, headers=headers["root"])
    duplicate = await auth_client.post(
        "/admin/users", json=body | {"email": "CLEO@example.org"}, headers=headers["root"]
    )
    short = await auth_client.post(
        "/admin/users",
        json=body | {"email": "dan@example.org", "password": "short"},
        headers=headers["root"],
    )

    assert created.status_code == 201, created.text
    assert created.json()["is_system_admin"] is False
    assert duplicate.status_code == 409
    assert short.status_code == 422
    user_id = created.json()["id"]
    detail = await auth_client.get(f"/admin/users/{user_id}", headers=headers["root"])
    assert detail.json()["email"] == "cleo@example.org"
    assert await login(auth_client, "cleo@example.org", OTHER_PASSWORD)
    async with session_factory() as session:
        hashes = list(await session.scalars(select(UserPasswordCredential.password_hash)))
    for response in (created, detail, duplicate, short):
        assert OTHER_PASSWORD not in response.text
        assert not any(value in response.text for value in hashes)


async def test_errors(auth_client: httpx.AsyncClient, headers: dict[str, dict[str, str]]) -> None:
    body = {"email": "cleo@example.org", "display_name": "Cleo", "password": TEST_PASSWORD}

    responses = {
        "list as user": await auth_client.get("/admin/users", headers=headers["ana"]),
        "create as user": await auth_client.post("/admin/users", json=body, headers=headers["ana"]),
        "unknown": await auth_client.get(f"/admin/users/{uuid.uuid4()}", headers=headers["root"]),
        "no token": await auth_client.get("/admin/users"),
    }

    assert {name: response.status_code for name, response in responses.items()} == {
        "list as user": 403,
        "create as user": 403,
        "unknown": 404,
        "no token": 401,
    }
