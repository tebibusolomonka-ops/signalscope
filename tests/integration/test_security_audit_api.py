import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from password_helpers import TEST_PASSWORD
from signalscope.domain.users.credential import UserPasswordCredential
from signalscope.domain.users.session import UserSession

pytestmark = pytest.mark.anyio


@pytest.fixture
async def setup(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> dict[str, str]:
    """Headers per user are stored under the user's name; organization IDs by slug."""
    found: dict[str, str] = {}
    for name in ("system", "owner", "admin", "member", "other"):
        await create_account(session_factory, f"{name}@example.org", system_admin=name == "system")
        found[name] = await login(auth_client, f"{name}@example.org")
    harbour = await auth_client.post(
        "/organizations",
        json={"name": "Harbour", "slug": "harbour"},
        headers=bearer(found["owner"]),
    )
    river = await auth_client.post(
        "/organizations", json={"name": "River", "slug": "river"}, headers=bearer(found["other"])
    )
    found["harbour"] = harbour.json()["id"]
    found["river"] = river.json()["id"]
    me = await auth_client.get("/auth/me", headers=bearer(found["admin"]))
    member = await auth_client.get("/auth/me", headers=bearer(found["member"]))
    for user_id, role in (
        (me.json()["user"]["id"], "admin"),
        (member.json()["user"]["id"], "member"),
    ):
        added = await auth_client.post(
            f"/organizations/{found['harbour']}/members",
            json={"user_id": user_id, "role": role},
            headers=bearer(found["owner"]),
        )
        assert added.status_code == 201
    return found


async def audit(client: httpx.AsyncClient, token: str, query: str = "") -> httpx.Response:
    return await client.get(f"/security/audit{query}", headers=bearer(token))


async def test_system_admin(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    setup: dict[str, str],
) -> None:
    everything = await audit(auth_client, setup["system"])
    logins = await audit(auth_client, setup["system"], "?action=auth.login&limit=2")
    organizations = await audit(auth_client, setup["system"], "?resource_type=organization")

    assert everything.status_code == 200, everything.text
    body = everything.json()
    actions = [item["action"] for item in body["items"]]
    assert "user.created" in actions and "organization.member_added" in actions
    assert set(body["items"][0]) == {
        "id",
        "actor",
        "organization_id",
        "action",
        "resource_type",
        "resource_id",
        "metadata",
        "created_at",
    }
    times = [item["created_at"] for item in body["items"]]
    assert times == sorted(times, reverse=True)
    assert (logins.json()["total"], len(logins.json()["items"])) == (5, 2)
    assert {item["resource_type"] for item in organizations.json()["items"]} == {"organization"}
    async with session_factory() as session:
        secrets = [TEST_PASSWORD, *setup.values()]
        secrets += list(await session.scalars(select(UserSession.token_hash)))
        secrets += list(await session.scalars(select(UserPasswordCredential.password_hash)))
    for secret in secrets:
        if secret not in (setup["harbour"], setup["river"]):
            assert secret not in everything.text


@pytest.mark.parametrize("name", ["owner", "admin"])
async def test_organization_managers(
    auth_client: httpx.AsyncClient, setup: dict[str, str], name: str
) -> None:
    own = await audit(auth_client, setup[name], f"?organization_id={setup['harbour']}")
    other = await audit(auth_client, setup[name], f"?organization_id={setup['river']}")
    missing = await audit(auth_client, setup[name])

    assert own.status_code == 200
    assert {item["organization_id"] for item in own.json()["items"]} == {setup["harbour"]}
    assert [item["action"] for item in own.json()["items"]] == [
        "organization.member_added",
        "organization.member_added",
        "organization.created",
    ]
    assert own.json()["items"][-1]["actor"]["email"] == "owner@example.org"
    assert other.status_code == 404
    assert missing.status_code == 422


async def test_errors(auth_client: httpx.AsyncClient, setup: dict[str, str]) -> None:
    harbour = setup["harbour"]
    responses = {
        "member": await audit(auth_client, setup["member"], f"?organization_id={harbour}"),
        "member without organization": await audit(auth_client, setup["member"]),
        "bad date": await audit(auth_client, setup["system"], "?created_from=yesterday"),
        "bad id": await audit(auth_client, setup["system"], "?organization_id=nope"),
        "reversed dates": await audit(
            auth_client,
            setup["system"],
            "?created_from=2026-02-01T00:00:00Z&created_to=2026-01-01T00:00:00Z",
        ),
        "no token": await auth_client.get("/security/audit"),
    }

    assert {name: response.status_code for name, response in responses.items()} == {
        "member": 403,
        "member without organization": 403,
        "bad date": 422,
        "bad id": 422,
        "reversed dates": 422,
        "no token": 401,
    }


async def test_date_range(auth_client: httpx.AsyncClient, setup: dict[str, str]) -> None:
    future = await audit(auth_client, setup["system"], "?created_from=2999-01-01T00:00:00")
    past = await audit(auth_client, setup["system"], "?created_to=2000-01-01T00:00:00Z")
    now = await audit(auth_client, setup["system"], "?created_from=2000-01-01T00:00:00Z")

    assert (future.json()["total"], past.json()["total"]) == (0, 0)
    assert now.json()["total"] > 0
