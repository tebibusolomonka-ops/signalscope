import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio


@pytest.fixture
async def people(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> dict[str, tuple[User, dict[str, str]]]:
    """Each user with the headers of a signed in session."""
    found = {}
    for name in ("owner", "admin", "member", "viewer", "outsider", "system"):
        email = f"{name}@example.org"
        user = await create_account(session_factory, email, system_admin=name == "system")
        found[name] = (user, bearer(await login(auth_client, email)))
    return found


async def create_organization(
    client: httpx.AsyncClient, people: dict[str, tuple[User, dict[str, str]]]
) -> str:
    response = await client.post(
        "/organizations",
        json={"name": "Harbour Watch", "slug": "harbour-watch"},
        headers=people["owner"][1],
    )
    assert response.status_code == 201, response.text
    organization_id: str = response.json()["id"]
    for name in ("admin", "member", "viewer"):
        added = await client.post(
            f"/organizations/{organization_id}/members",
            json={"user_id": str(people[name][0].id), "role": name},
            headers=people["owner"][1],
        )
        assert added.status_code == 201, added.text
    return organization_id


async def test_create_list_get_and_members(
    auth_client: httpx.AsyncClient, people: dict[str, tuple[User, dict[str, str]]]
) -> None:
    organization_id = await create_organization(auth_client, people)

    mine = (await auth_client.get("/organizations", headers=people["viewer"][1])).json()
    detail = await auth_client.get(f"/organizations/{organization_id}", headers=people["member"][1])
    members = (
        await auth_client.get(
            f"/organizations/{organization_id}/members", headers=people["viewer"][1]
        )
    ).json()

    assert [(item["organization"]["slug"], item["role"]) for item in mine] == [
        ("harbour-watch", "viewer")
    ]
    assert detail.json()["created_by_user_id"] == str(people["owner"][0].id)
    assert [member["role"] for member in members] == ["owner", "admin", "member", "viewer"]
    assert set(members[0]["user"]) == {"id", "email", "display_name"}
    outsider = await auth_client.get("/organizations", headers=people["outsider"][1])
    assert outsider.json() == []


async def test_role_changes_and_removal(
    auth_client: httpx.AsyncClient, people: dict[str, tuple[User, dict[str, str]]]
) -> None:
    organization_id = await create_organization(auth_client, people)
    members = f"/organizations/{organization_id}/members"
    member_id = str(people["member"][0].id)

    promoted = await auth_client.patch(
        f"{members}/{member_id}", json={"role": "viewer"}, headers=people["admin"][1]
    )
    removed = await auth_client.delete(f"{members}/{member_id}", headers=people["admin"][1])

    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "viewer"
    assert removed.status_code == 204
    listed = (await auth_client.get(members, headers=people["owner"][1])).json()
    assert member_id not in [member["user"]["id"] for member in listed]


async def test_permission_rules(
    auth_client: httpx.AsyncClient, people: dict[str, tuple[User, dict[str, str]]]
) -> None:
    organization_id = await create_organization(auth_client, people)
    members = f"/organizations/{organization_id}/members"
    outsider_id = str(people["outsider"][0].id)
    owner_id = str(people["owner"][0].id)

    responses: list[tuple[str, httpx.Response]] = [
        (
            "admin adds admin",
            await auth_client.post(
                members, json={"user_id": outsider_id, "role": "admin"}, headers=people["admin"][1]
            ),
        ),
        (
            "admin demotes owner",
            await auth_client.patch(
                f"{members}/{owner_id}", json={"role": "member"}, headers=people["admin"][1]
            ),
        ),
        (
            "member adds",
            await auth_client.post(
                members, json={"user_id": outsider_id}, headers=people["member"][1]
            ),
        ),
        (
            "viewer removes",
            await auth_client.delete(
                f"{members}/{people['member'][0].id}", headers=people["viewer"][1]
            ),
        ),
    ]
    assert [(name, response.status_code) for name, response in responses] == [
        (name, 403) for name, _ in responses
    ]

    outsider = await auth_client.get(members, headers=people["outsider"][1])
    assert outsider.status_code == 404


async def test_last_owner_and_errors(
    auth_client: httpx.AsyncClient, people: dict[str, tuple[User, dict[str, str]]]
) -> None:
    organization_id = await create_organization(auth_client, people)
    members = f"/organizations/{organization_id}/members"
    owner_id = str(people["owner"][0].id)

    last_owner = await auth_client.delete(f"{members}/{owner_id}", headers=people["owner"][1])
    duplicate = await auth_client.post(
        members, json={"user_id": str(people["member"][0].id)}, headers=people["owner"][1]
    )
    unknown_user = await auth_client.post(
        members, json={"user_id": str(uuid.uuid4())}, headers=people["owner"][1]
    )
    unknown_organization = await auth_client.get(
        f"/organizations/{uuid.uuid4()}", headers=people["owner"][1]
    )
    no_token = await auth_client.get("/organizations")

    assert last_owner.status_code == 409
    assert last_owner.json()["error"]["message"] == "An organization must keep at least one owner."
    assert duplicate.status_code == 409
    assert unknown_user.status_code == 404
    assert unknown_organization.status_code == 404
    assert no_token.status_code == 401


async def test_system_admin_recovery(
    auth_client: httpx.AsyncClient, people: dict[str, tuple[User, dict[str, str]]]
) -> None:
    organization_id = await create_organization(auth_client, people)
    members = f"/organizations/{organization_id}/members"

    body: dict[str, Any] = {"user_id": str(people["outsider"][0].id), "role": "owner"}
    added = await auth_client.post(members, json=body, headers=people["system"][1])
    seen = await auth_client.get(f"/organizations/{organization_id}", headers=people["system"][1])

    assert added.status_code == 201, added.text
    assert added.json()["role"] == "owner"
    assert seen.status_code == 200
