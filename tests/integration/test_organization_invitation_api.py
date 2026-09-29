import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from signalscope.domain.organizations.invitation import OrganizationInvitation
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio

People = dict[str, tuple[User, dict[str, str]]]


@pytest.fixture
async def people(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> People:
    found = {}
    for name in ("owner", "admin", "member", "outsider"):
        email = f"{name}@example.org"
        user = await create_account(session_factory, email)
        found[name] = (user, bearer(await login(auth_client, email)))
    return found


@pytest.fixture
async def invitations(auth_client: httpx.AsyncClient, people: People) -> str:
    organization = await auth_client.post(
        "/organizations", json={"name": "Harbour", "slug": "harbour"}, headers=people["owner"][1]
    )
    organization_id = organization.json()["id"]
    for name in ("admin", "member"):
        added = await auth_client.post(
            f"/organizations/{organization_id}/members",
            json={"user_id": str(people[name][0].id), "role": name},
            headers=people["owner"][1],
        )
        assert added.status_code == 201
    return f"/organizations/{organization_id}/invitations"


async def test_create_list_and_revoke(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    people: People,
    invitations: str,
) -> None:
    owner = people["owner"][1]

    created = await auth_client.post(
        invitations, json={"email": "New@Example.org", "role": "admin"}, headers=owner
    )
    second = await auth_client.post(
        invitations, json={"email": "other@example.org"}, headers=people["admin"][1]
    )

    assert created.status_code == 201, created.text
    body = created.json()
    token = body["invitation_token"]
    assert len(token) >= 40
    assert body["invitation"]["email"] == "new@example.org"
    assert (body["invitation"]["role"], body["invitation"]["status"]) == ("admin", "pending")
    assert second.json()["invitation"]["role"] == "member"
    async with session_factory() as session:
        hashes = list(await session.scalars(select(OrganizationInvitation.token_hash)))

    listed = await auth_client.get(invitations, headers=people["admin"][1])
    assert [item["email"] for item in listed.json()] == ["other@example.org", "new@example.org"]
    for secret in [token, second.json()["invitation_token"], *hashes]:
        assert secret not in listed.text
    assert not any("token" in field for field in listed.json()[0])

    invitation_id = second.json()["invitation"]["id"]
    revoked = await auth_client.delete(f"{invitations}/{invitation_id}", headers=owner)
    assert revoked.status_code == 204
    by_status = {
        status: [
            item["email"]
            for item in (
                await auth_client.get(f"{invitations}?status={status}", headers=owner)
            ).json()
        ]
        for status in ("pending", "revoked", "accepted", "expired")
    }
    assert by_status == {
        "pending": ["new@example.org"],
        "revoked": ["other@example.org"],
        "accepted": [],
        "expired": [],
    }


async def test_errors(auth_client: httpx.AsyncClient, people: People, invitations: str) -> None:
    owner = people["owner"][1]
    await auth_client.post(invitations, json={"email": "new@example.org"}, headers=owner)

    responses = {
        "admin invites admin": await auth_client.post(
            invitations,
            json={"email": "x@example.org", "role": "admin"},
            headers=people["admin"][1],
        ),
        "member invites": await auth_client.post(
            invitations, json={"email": "x@example.org"}, headers=people["member"][1]
        ),
        "member lists": await auth_client.get(invitations, headers=people["member"][1]),
        "outsider lists": await auth_client.get(invitations, headers=people["outsider"][1]),
        "duplicate": await auth_client.post(
            invitations, json={"email": "NEW@example.org"}, headers=owner
        ),
        "existing member": await auth_client.post(
            invitations, json={"email": "member@example.org"}, headers=owner
        ),
        "owner role": await auth_client.post(
            invitations, json={"email": "x@example.org", "role": "owner"}, headers=owner
        ),
        "bad email": await auth_client.post(invitations, json={"email": "nobody"}, headers=owner),
        "unknown invitation": await auth_client.delete(
            f"{invitations}/{uuid.uuid4()}", headers=owner
        ),
        "unknown organization": await auth_client.get(
            f"/organizations/{uuid.uuid4()}/invitations", headers=owner
        ),
        "bad status": await auth_client.get(f"{invitations}?status=open", headers=owner),
        "no token": await auth_client.get(invitations),
    }

    assert {name: response.status_code for name, response in responses.items()} == {
        "admin invites admin": 403,
        "member invites": 403,
        "member lists": 403,
        "outsider lists": 404,
        "duplicate": 409,
        "existing member": 409,
        "owner role": 422,
        "bad email": 422,
        "unknown invitation": 404,
        "unknown organization": 404,
        "bad status": 422,
        "no token": 401,
    }
