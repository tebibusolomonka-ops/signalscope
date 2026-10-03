import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from password_helpers import TEST_PASSWORD
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.users.credential import UserPasswordCredential
from signalscope.domain.users.session import UserSession

pytestmark = pytest.mark.anyio


async def events(session_factory: async_sessionmaker[AsyncSession]) -> list[SecurityAuditEvent]:
    async with session_factory() as session:
        found = await session.scalars(
            select(SecurityAuditEvent).order_by(SecurityAuditEvent.created_at)
        )
        return list(found)


async def actions(session_factory: async_sessionmaker[AsyncSession]) -> list[str]:
    return [event.action for event in await events(session_factory)]


async def test_account_and_session_events(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user = await create_account(session_factory, "ana@example.org", system_admin=True)
    token = await login(auth_client, "ana@example.org")
    await login(auth_client, "ana@example.org")
    failed = await auth_client.post(
        "/auth/login", json={"email": "ana@example.org", "password": "not the password"}
    )
    assert failed.status_code == 401

    assert (await auth_client.post("/auth/logout", headers=bearer(token))).status_code == 204
    other = await login(auth_client, "ana@example.org")
    assert (await auth_client.post("/auth/logout-all", headers=bearer(other))).status_code == 204

    found = await events(session_factory)
    assert [event.action for event in found] == [
        "user.created",
        "auth.login",
        "auth.login",
        "authentication_login_failed",
        "auth.logout",
        "auth.login",
        "auth.logout_all",
    ]
    created, first_login = found[0], found[1]
    assert (created.actor_user_id, created.resource_id) == (None, user.id)
    assert created.details == {"system_admin": True}
    async with session_factory() as session:
        session_ids = set(await session.scalars(select(UserSession.id)))
    assert first_login.actor_user_id == user.id
    assert first_login.resource_type == "user_session"
    assert first_login.resource_id in session_ids
    assert found[-1].details == {"revoked_sessions": 2}


async def test_organization_and_collaborator_events(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    owner = await create_account(session_factory, "owner@example.org")
    member = await create_account(session_factory, "member@example.org")
    headers = bearer(await login(auth_client, "owner@example.org"))
    organization = await auth_client.post(
        "/organizations", json={"name": "Harbour", "slug": "harbour"}, headers=headers
    )
    organization_id = organization.json()["id"]
    members = f"/organizations/{organization_id}/members"
    await auth_client.post(members, json={"user_id": str(member.id)}, headers=headers)
    await auth_client.patch(f"{members}/{member.id}", json={"role": "viewer"}, headers=headers)
    investigation = await auth_client.post(
        "/investigations",
        json={"title": "Floods", "organization_id": organization_id},
        headers=headers,
    )
    collaborators = f"/investigations/{investigation.json()['id']}/members"
    await auth_client.post(collaborators, json={"user_id": str(member.id)}, headers=headers)
    await auth_client.patch(
        f"{collaborators}/{member.id}", json={"role": "editor"}, headers=headers
    )
    await auth_client.delete(f"{collaborators}/{member.id}", headers=headers)
    await auth_client.delete(f"{members}/{member.id}", headers=headers)

    found = [
        event for event in await events(session_factory) if not event.action.startswith("auth.")
    ]
    summary = [(event.action, event.details) for event in found if event.action != "user.created"]
    assert summary == [
        ("organization.created", {}),
        ("organization.member_added", {"user_id": str(member.id), "role": "member"}),
        (
            "organization.member_role_changed",
            {"user_id": str(member.id), "old_role": "member", "new_role": "viewer"},
        ),
        ("investigation.collaborator_added", {"user_id": str(member.id), "role": "viewer"}),
        (
            "investigation.collaborator_role_changed",
            {"user_id": str(member.id), "old_role": "viewer", "new_role": "editor"},
        ),
        ("investigation.collaborator_removed", {"user_id": str(member.id), "role": "editor"}),
        ("organization.member_removed", {"user_id": str(member.id), "role": "viewer"}),
    ]
    for event in found:
        if event.action != "user.created":
            assert event.actor_user_id == owner.id
            assert str(event.organization_id) == organization_id
    assert {event.resource_type for event in found} >= {"organization", "investigation"}


async def test_refused_changes_record_nothing(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    owner = await create_account(session_factory, "owner@example.org")
    headers = bearer(await login(auth_client, "owner@example.org"))
    organization = await auth_client.post(
        "/organizations", json={"name": "Harbour", "slug": "harbour"}, headers=headers
    )
    members = f"/organizations/{organization.json()['id']}/members"
    before = await actions(session_factory)

    duplicate = await auth_client.post(members, json={"user_id": str(owner.id)}, headers=headers)
    last_owner = await auth_client.delete(f"{members}/{owner.id}", headers=headers)
    same_slug = await auth_client.post(
        "/organizations", json={"name": "Other", "slug": "harbour"}, headers=headers
    )
    unknown = await auth_client.delete(f"/auth/sessions/{uuid.uuid4()}", headers=headers)

    assert [r.status_code for r in (duplicate, last_owner, same_slug, unknown)] == [
        409,
        409,
        409,
        404,
    ]
    assert await actions(session_factory) == before


async def test_no_secrets_in_audit_events(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await create_account(session_factory, "ana@example.org")
    token = await login(auth_client, "ana@example.org")
    await auth_client.post("/auth/logout-all", headers=bearer(token))

    async with session_factory() as session:
        secrets = [TEST_PASSWORD, token, "Bearer"]
        secrets += list(await session.scalars(select(UserSession.token_hash)))
        secrets += list(await session.scalars(select(UserPasswordCredential.password_hash)))
    stored: list[dict[str, Any]] = [
        {
            "action": event.action,
            "resource_type": event.resource_type,
            "metadata": event.details,
        }
        for event in await events(session_factory)
    ]
    dumped = json.dumps(stored)
    assert len(stored) == 3
    for secret in secrets:
        assert secret not in dumped
