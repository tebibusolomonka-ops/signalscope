import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from password_helpers import TEST_PASSWORD

pytestmark = pytest.mark.anyio


async def test_access_summary(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers = {}
    users = {}
    for name in ("owner", "admin", "member", "viewer", "outsider", "system"):
        user = await create_account(
            session_factory, f"{name}@example.org", system_admin=name == "system"
        )
        users[name] = str(user.id)
        headers[name] = bearer(await login(auth_client, f"{name}@example.org"))
    organization = await auth_client.post(
        "/organizations", json={"name": "Harbour", "slug": "harbour"}, headers=headers["owner"]
    )
    organization_id = organization.json()["id"]
    for name in ("admin", "member", "viewer"):
        await auth_client.post(
            f"/organizations/{organization_id}/members",
            json={"user_id": users[name], "role": name},
            headers=headers["owner"],
        )
    invited = await auth_client.post(
        f"/organizations/{organization_id}/invitations",
        json={"email": "new@example.org"},
        headers=headers["owner"],
    )
    investigation = await auth_client.post(
        "/investigations",
        json={"title": "Floods", "organization_id": organization_id},
        headers=headers["member"],
    )
    await auth_client.post(
        f"/investigations/{investigation.json()['id']}/members",
        json={"user_id": users["viewer"]},
        headers=headers["member"],
    )
    path = f"/organizations/{organization_id}/access-summary"

    responses = {name: await auth_client.get(path, headers=headers[name]) for name in headers}

    assert {name: response.status_code for name, response in responses.items()} == {
        "owner": 200,
        "admin": 200,
        "member": 403,
        "viewer": 403,
        "outsider": 404,
        "system": 200,
    }
    body = responses["admin"].json()
    assert body["organization"]["id"] == organization_id
    assert body["members"] == {"total": 4, "owner": 1, "admin": 1, "member": 1, "viewer": 1}
    assert body["member_status"] == {"active": 4, "inactive": 0}
    assert body["invitations"] == {"pending": 1, "accepted": 0, "revoked": 0, "expired": 0}
    assert body["investigations"] == {"open": 1, "closed": 0}
    assert body["collaborators"] == {"owner": 1, "editor": 0, "viewer": 1}
    assert responses["system"].json() == body
    for secret in (invited.json()["invitation_token"], TEST_PASSWORD, "hash", "token"):
        assert secret not in responses["owner"].text
    unknown = await auth_client.get(
        f"/organizations/{uuid.uuid4()}/access-summary", headers=headers["system"]
    )
    assert unknown.status_code == 404
