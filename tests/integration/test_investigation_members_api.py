import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio

People = dict[str, tuple[User, dict[str, str]]]


@pytest.fixture
async def people(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> People:
    found = {}
    for name in ("lead", "admin", "writer", "reader", "member", "outsider"):
        email = f"{name}@example.org"
        user = await create_account(session_factory, email)
        found[name] = (user, bearer(await login(auth_client, email)))
    return found


@pytest.fixture
async def investigation(auth_client: httpx.AsyncClient, people: People) -> str:
    """An investigation by the lead, in an organization where admin is an admin."""
    organization = await auth_client.post(
        "/organizations",
        json={"name": "Harbour Watch", "slug": "harbour-watch"},
        headers=people["lead"][1],
    )
    organization_id = organization.json()["id"]
    for name in ("admin", "writer", "reader", "member"):
        role = "admin" if name == "admin" else "member"
        added = await auth_client.post(
            f"/organizations/{organization_id}/members",
            json={"user_id": str(people[name][0].id), "role": role},
            headers=people["lead"][1],
        )
        assert added.status_code == 201, added.text
    created = await auth_client.post(
        "/investigations",
        json={"title": "Floods", "organization_id": organization_id},
        headers=people["member"][1],
    )
    assert created.status_code == 201, created.text
    investigation_id: str = created.json()["id"]
    return investigation_id


def uid(people: People, name: str) -> str:
    return str(people[name][0].id)


async def test_add_list_change_and_remove(
    auth_client: httpx.AsyncClient, people: People, investigation: str
) -> None:
    members = f"/investigations/{investigation}/members"
    owner = people["member"][1]

    writer = await auth_client.post(
        members, json={"user_id": uid(people, "writer"), "role": "editor"}, headers=owner
    )
    reader = await auth_client.post(members, json={"user_id": uid(people, "reader")}, headers=owner)
    listed = await auth_client.get(members, headers=people["reader"][1])

    assert writer.status_code == 201, writer.text
    assert reader.json()["role"] == "viewer"
    assert [(item["user"]["id"], item["role"]) for item in listed.json()] == [
        (uid(people, "member"), "owner"),
        (uid(people, "writer"), "editor"),
        (uid(people, "reader"), "viewer"),
    ]
    assert set(listed.json()[0]["user"]) == {"id", "email", "display_name"}

    changed = await auth_client.patch(
        f"{members}/{uid(people, 'reader')}", json={"role": "editor"}, headers=owner
    )
    edit = await auth_client.patch(
        f"/investigations/{investigation}", json={"title": "Harbour"}, headers=people["reader"][1]
    )
    removed = await auth_client.delete(f"{members}/{uid(people, 'writer')}", headers=owner)
    hidden = await auth_client.get(f"/investigations/{investigation}", headers=people["writer"][1])

    assert changed.json()["role"] == "editor"
    assert edit.status_code == 200
    assert removed.status_code == 204
    assert hidden.status_code == 404


async def test_who_may_manage(
    auth_client: httpx.AsyncClient, people: People, investigation: str
) -> None:
    members = f"/investigations/{investigation}/members"
    added = await auth_client.post(
        members,
        json={"user_id": uid(people, "writer"), "role": "editor"},
        headers=people["member"][1],
    )
    assert added.status_code == 201

    by_editor = await auth_client.post(
        members, json={"user_id": uid(people, "reader")}, headers=people["writer"][1]
    )
    by_outsider = await auth_client.get(members, headers=people["outsider"][1])
    by_organization_admin = await auth_client.post(
        members, json={"user_id": uid(people, "reader")}, headers=people["admin"][1]
    )
    by_organization_owner = await auth_client.patch(
        f"{members}/{uid(people, 'reader')}", json={"role": "owner"}, headers=people["lead"][1]
    )

    assert by_editor.status_code == 403
    assert by_outsider.status_code == 404
    assert by_organization_admin.status_code == 201
    assert by_organization_owner.status_code == 200
    assert by_organization_owner.json()["role"] == "owner"


async def test_rules(auth_client: httpx.AsyncClient, people: People, investigation: str) -> None:
    members = f"/investigations/{investigation}/members"
    owner = people["member"][1]

    last_owner = await auth_client.patch(
        f"{members}/{uid(people, 'member')}", json={"role": "viewer"}, headers=owner
    )
    remove_last = await auth_client.delete(f"{members}/{uid(people, 'member')}", headers=owner)
    duplicate = await auth_client.post(
        members, json={"user_id": uid(people, "member")}, headers=owner
    )
    not_in_organization = await auth_client.post(
        members, json={"user_id": uid(people, "outsider")}, headers=owner
    )
    missing = await auth_client.delete(f"{members}/{uid(people, 'reader')}", headers=owner)

    assert last_owner.status_code == 409
    assert last_owner.json()["error"]["message"] == "An investigation must keep at least one owner."
    assert remove_last.status_code == 409
    assert duplicate.status_code == 409
    assert not_in_organization.status_code == 404
    assert missing.status_code == 404


async def test_closed_investigation_can_be_shared(
    auth_client: httpx.AsyncClient, people: People, investigation: str
) -> None:
    owner = people["member"][1]
    closed = await auth_client.patch(
        f"/investigations/{investigation}", json={"status": "closed"}, headers=owner
    )
    assert closed.status_code == 200

    added = await auth_client.post(
        f"/investigations/{investigation}/members",
        json={"user_id": uid(people, "reader")},
        headers=owner,
    )
    read = await auth_client.get(f"/investigations/{investigation}", headers=people["reader"][1])

    assert added.status_code == 201, added.text
    assert read.json()["status"] == "closed"
