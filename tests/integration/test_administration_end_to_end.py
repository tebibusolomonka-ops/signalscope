"""User administration, invitations, lifecycle and audit, through the API only."""

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account
from password_helpers import OTHER_PASSWORD, TEST_PASSWORD
from signalscope.domain.organizations.invitation import OrganizationInvitation
from signalscope.domain.users.credential import UserPasswordCredential
from signalscope.domain.users.session import UserSession

pytestmark = pytest.mark.anyio

NEW_PASSWORD = "the lead changed this long password"


class Recorder:
    """Sends requests and keeps every answer, to check them for secrets at the end."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.answers: list[str] = []

    async def call(
        self, method: str, path: str, token: str | None = None, body: Any = None, expect: int = 200
    ) -> Any:
        headers = {} if token is None else bearer(token)
        response = await self.client.request(method, path, json=body, headers=headers)
        assert response.status_code == expect, (method, path, response.status_code)
        self.answers.append(response.text)
        return None if response.status_code == 204 else response.json()

    async def login(self, email: str, password: str) -> str:
        body = await self.call("POST", "/auth/login", body={"email": email, "password": password})
        token: str = body["access_token"]
        return token


async def test_administration_flow(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    api = Recorder(auth_client)
    await create_account(session_factory, "root@example.org", system_admin=True)
    root = await api.login("root@example.org", TEST_PASSWORD)

    # A system admin creates the other accounts through the API.
    user_ids = {}
    for name in ("lead", "ana", "cleo"):
        created = await api.call(
            "POST",
            "/admin/users",
            root,
            {
                "email": f"{name}@example.org",
                "display_name": name.title(),
                "password": OTHER_PASSWORD,
            },
            expect=201,
        )
        user_ids[name] = created["id"]
    lead = await api.login("lead@example.org", OTHER_PASSWORD)
    lead_phone = await api.login("lead@example.org", OTHER_PASSWORD)
    ana = await api.login("ana@example.org", OTHER_PASSWORD)

    # The lead makes an organization and an admin; the admin invites Cleo.
    organization = await api.call(
        "POST", "/organizations", lead, {"name": "Harbour", "slug": "harbour"}, expect=201
    )
    organization_path = f"/organizations/{organization['id']}"
    await api.call(
        "POST",
        f"{organization_path}/members",
        lead,
        {"user_id": user_ids["ana"], "role": "admin"},
        expect=201,
    )
    invited = await auth_client.post(
        f"{organization_path}/invitations",
        json={"email": "cleo@example.org", "role": "member"},
        headers=bearer(ana),
    )
    assert invited.status_code == 201
    invitation_token = invited.json()["invitation_token"]
    cleo = await api.login("cleo@example.org", OTHER_PASSWORD)
    joined = await api.call(
        "POST", "/organization-invitations/accept", cleo, {"token": invitation_token}
    )
    assert joined["role"] == "member"
    await api.call(
        "POST", "/organization-invitations/accept", cleo, {"token": invitation_token}, expect=404
    )

    # The lead changes their password: the phone session ends, this one stays.
    await api.call(
        "POST",
        "/auth/change-password",
        lead,
        {"current_password": OTHER_PASSWORD, "new_password": NEW_PASSWORD},
        expect=204,
    )
    await api.call("GET", "/auth/me", lead)
    await api.call("GET", "/auth/me", lead_phone, expect=401)
    await api.call(
        "POST",
        "/auth/login",
        body={"email": "lead@example.org", "password": OTHER_PASSWORD},
        expect=401,
    )
    await api.login("lead@example.org", NEW_PASSWORD)

    # The system admin deactivates and reactivates Ana.
    status_path = f"/admin/users/{user_ids['ana']}/status"
    await api.call("PATCH", status_path, root, {"is_active": False})
    await api.call("GET", "/auth/me", ana, expect=401)
    await api.call("PATCH", status_path, root, {"is_active": True})
    await api.call("GET", "/auth/me", ana, expect=401)
    ana = await api.login("ana@example.org", OTHER_PASSWORD)

    # An investigation shared with collaborators.
    investigation = await api.call(
        "POST",
        "/investigations",
        lead,
        {"title": "Floods", "organization_id": organization["id"]},
        expect=201,
    )
    members_path = f"/investigations/{investigation['id']}/members"
    await api.call(
        "POST", members_path, lead, {"user_id": user_ids["cleo"], "role": "editor"}, expect=201
    )
    await api.call("POST", members_path, lead, {"user_id": user_ids["ana"]}, expect=201)

    summary = await api.call("GET", f"{organization_path}/access-summary", ana)
    assert summary["members"] == {"total": 3, "owner": 1, "admin": 1, "member": 1, "viewer": 0}
    assert summary["invitations"]["accepted"] == 1
    assert summary["investigations"] == {"open": 1, "closed": 0}
    assert summary["collaborators"] == {"owner": 1, "editor": 1, "viewer": 1}

    organization_audit = await api.call(
        "GET", f"/security/audit?organization_id={organization['id']}&limit=100", lead
    )
    assert {item["action"] for item in organization_audit["items"]} >= {
        "organization.created",
        "organization.member_added",
        "organization.invitation_created",
        "organization.invitation_accepted",
        "investigation.collaborator_added",
    }
    everything = await api.call("GET", "/security/audit?limit=100", root)
    assert {item["action"] for item in everything["items"]} >= {
        "user.created",
        "auth.login",
        "auth.password_changed",
        "user.deactivated",
        "user.reactivated",
    }
    await api.call("GET", "/security/audit", cleo, expect=403)

    # No answer holds a password, a hash or a bearer token. The invitation
    # token appeared once, in the answer that created it, and never again.
    async with session_factory() as session:
        hashes = list(await session.scalars(select(UserSession.token_hash)))
        hashes += list(await session.scalars(select(UserPasswordCredential.password_hash)))
        hashes += list(await session.scalars(select(OrganizationInvitation.token_hash)))
    secrets = [TEST_PASSWORD, OTHER_PASSWORD, NEW_PASSWORD, invitation_token, *hashes]
    secrets += [root, lead, lead_phone, ana, cleo]
    for answer in api.answers:
        for secret in secrets:
            if secret in answer:
                # Only the login answers carry their own bearer token.
                assert '"access_token"' in answer and secret in (root, lead, lead_phone, ana, cleo)
    assert invited.text.count(invitation_token) == 1


async def test_auth_disabled_still_works(client: httpx.AsyncClient) -> None:
    created = await client.post("/investigations", json={"title": "Floods"})
    admin = await client.get("/admin/users")
    audit = await client.get("/security/audit")

    assert created.status_code == 201
    assert (await client.get(f"/investigations/{created.json()['id']}")).status_code == 200
    assert (admin.status_code, audit.status_code) == (503, 503)
