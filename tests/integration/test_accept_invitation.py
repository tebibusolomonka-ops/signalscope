import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.organizations.invitation import OrganizationInvitation
from signalscope.domain.organizations.membership import OrganizationMembership

pytestmark = pytest.mark.anyio

ACCEPT = "/organization-invitations/accept"


@dataclass
class Setup:
    owner: dict[str, str]
    ana: dict[str, str]
    ben: dict[str, str]
    organization_id: str

    @property
    def invitations(self) -> str:
        return f"/organizations/{self.organization_id}/invitations"


@pytest.fixture
async def setup(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> Setup:
    for name in ("owner", "ana", "ben"):
        await create_account(session_factory, f"{name}@example.org")
    owner = bearer(await login(auth_client, "owner@example.org"))
    organization = await auth_client.post(
        "/organizations", json={"name": "Harbour", "slug": "harbour"}, headers=owner
    )
    return Setup(
        owner=owner,
        ana=bearer(await login(auth_client, "ana@example.org")),
        ben=bearer(await login(auth_client, "ben@example.org")),
        organization_id=organization.json()["id"],
    )


async def invite(client: httpx.AsyncClient, setup: Setup, email: str, role: str) -> tuple[str, str]:
    response = await client.post(
        setup.invitations, json={"email": email, "role": role}, headers=setup.owner
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["invitation"]["id"], body["invitation_token"]


async def accept(client: httpx.AsyncClient, headers: dict[str, str], token: str) -> httpx.Response:
    return await client.post(ACCEPT, json={"token": token}, headers=headers)


async def test_accept(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    setup: Setup,
) -> None:
    invitation_id, token = await invite(auth_client, setup, "ANA@example.org", "viewer")

    wrong_user = await accept(auth_client, setup.ben, token)
    accepted = await accept(auth_client, setup.ana, token)
    replay = await accept(auth_client, setup.ana, token)

    assert wrong_user.status_code == 403
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["role"] == "viewer"
    assert accepted.json()["organization"]["id"] == setup.organization_id
    assert replay.status_code == 404
    assert replay.json()["error"]["message"] == "Invitation was not found or can no longer be used."
    listed = await auth_client.get(
        f"{setup.invitations}?status=accepted",
        headers=setup.owner,
    )
    assert [item["id"] for item in listed.json()] == [invitation_id]
    mine = await auth_client.get("/organizations", headers=setup.ana)
    assert [item["role"] for item in mine.json()] == ["viewer"]

    async with session_factory() as session:
        event = await session.scalar(
            select(SecurityAuditEvent).where(
                SecurityAuditEvent.action == "organization.invitation_accepted"
            )
        )
        token_hash = await session.scalar(
            select(OrganizationInvitation.token_hash).where(
                OrganizationInvitation.id == uuid.UUID(invitation_id)
            )
        )
    assert event is not None
    assert str(event.organization_id) == setup.organization_id
    dumped = json.dumps([event.action, event.resource_type, event.details])
    assert token not in dumped and str(token_hash) not in dumped
    assert event.details == {"role": "viewer"}


async def test_unusable_tokens(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    setup: Setup,
) -> None:
    expired_id, expired = await invite(auth_client, setup, "ana@example.org", "member")
    async with session_factory() as session:
        await session.execute(
            update(OrganizationInvitation)
            .where(OrganizationInvitation.id == uuid.UUID(expired_id))
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()
    revoked_id, revoked = await invite(auth_client, setup, "ana@example.org", "member")
    await auth_client.delete(
        f"{setup.invitations}/{revoked_id}",
        headers=setup.owner,
    )

    for token in (expired, revoked, "not a real token"):
        response = await accept(auth_client, setup.ana, token)
        assert response.status_code == 404
    assert (await auth_client.post(ACCEPT, json={"token": revoked})).status_code == 401
    async with session_factory() as session:
        members = list(await session.scalars(select(OrganizationMembership.user_id)))
    assert len(members) == 1


async def test_existing_member_is_a_conflict(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    setup: Setup,
) -> None:
    invitation_id, token = await invite(auth_client, setup, "ana@example.org", "admin")
    me = await auth_client.get("/auth/me", headers=setup.ana)
    added = await auth_client.post(
        setup.invitations.replace("invitations", "members"),
        json={"user_id": me.json()["user"]["id"], "role": "viewer"},
        headers=setup.owner,
    )
    assert added.status_code == 201

    response = await accept(auth_client, setup.ana, token)

    assert response.status_code == 409
    async with session_factory() as session:
        invitation = await session.get_one(OrganizationInvitation, uuid.UUID(invitation_id))
        roles = list(await session.scalars(select(OrganizationMembership.role)))
    # Nothing changed: the invitation is still pending and the role stays.
    assert invitation.accepted_at is None
    assert sorted(roles) == ["owner", "viewer"]
