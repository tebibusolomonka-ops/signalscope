"""The whole sign in and access flow, from the bootstrap command to audit events."""

import io
import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from auth_helpers import bearer, login
from password_helpers import OTHER_PASSWORD, TEST_PASSWORD, fast_hasher
from signalscope.cli import create_user
from signalscope.core.settings import Settings
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.users.credential import UserPasswordCredential
from signalscope.domain.users.session import UserSession

pytestmark = pytest.mark.anyio


async def bootstrap(settings: Settings, email: str, password: str, *options: str) -> str:
    """Run create-user with the password on standard input, and return the user ID."""
    out, err = io.StringIO(), io.StringIO()
    code = await create_user(
        settings,
        email,
        out,
        err,
        system_admin="--system-admin" in options,
        password_stdin=True,
        stdin=io.StringIO(password + "\n"),
        hasher=fast_hasher(),
    )
    assert (code, err.getvalue()) == (0, "")
    assert password not in out.getvalue()
    return out.getvalue().splitlines()[0].removeprefix("User ID: ")


async def test_full_flow(
    auth_client: httpx.AsyncClient,
    database_engine: AsyncEngine,
    migrated_database: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = Settings(database_url=migrated_database.database_url)
    await bootstrap(settings, "admin@example.org", TEST_PASSWORD, "--system-admin")
    analyst_id = await bootstrap(settings, "analyst@example.org", OTHER_PASSWORD)
    reader_id = await bootstrap(settings, "reader@example.org", OTHER_PASSWORD)

    # Every protected route refuses a request without a token.
    assert (await auth_client.get("/investigations")).status_code == 401
    admin = bearer(await login(auth_client, "admin@example.org"))
    analyst_token = await login(auth_client, "analyst@example.org", OTHER_PASSWORD)
    analyst = bearer(analyst_token)
    reader = bearer(await login(auth_client, "reader@example.org", OTHER_PASSWORD))
    me = await auth_client.get("/auth/me", headers=analyst)
    assert me.json()["user"]["id"] == analyst_id

    # The admin makes an organization and adds the analyst and reader.
    organization = await auth_client.post(
        "/organizations", json={"name": "Harbour Watch", "slug": "harbour-watch"}, headers=admin
    )
    organization_id = organization.json()["id"]
    for user_id in (analyst_id, reader_id):
        added = await auth_client.post(
            f"/organizations/{organization_id}/members", json={"user_id": user_id}, headers=admin
        )
        assert added.status_code == 201, added.text

    # The analyst starts an investigation and shares it with the reader.
    created = await auth_client.post(
        "/investigations",
        json={"title": "Harbour floods", "organization_id": organization_id},
        headers=analyst,
    )
    assert created.status_code == 201, created.text
    investigation = f"/investigations/{created.json()['id']}"
    assert (await auth_client.get("/investigations", headers=reader)).json()["total"] == 0
    shared = await auth_client.post(
        f"{investigation}/members", json={"user_id": reader_id}, headers=analyst
    )
    assert shared.json()["role"] == "viewer"
    assert (await auth_client.get("/investigations", headers=reader)).json()["total"] == 1
    assert (await auth_client.get(f"{investigation}/export", headers=reader)).status_code == 200
    refused = await auth_client.patch(investigation, json={"title": "Mine"}, headers=reader)
    assert refused.status_code == 403
    edited = await auth_client.patch(investigation, json={"title": "Floods"}, headers=analyst)
    assert edited.status_code == 200

    # The analyst ends every session.
    sessions = await auth_client.get("/auth/sessions", headers=analyst)
    assert [item["current_session"] for item in sessions.json()] == [True]
    assert analyst_token not in sessions.text
    assert (await auth_client.post("/auth/logout-all", headers=analyst)).status_code == 204
    assert (await auth_client.get(investigation, headers=analyst)).status_code == 401

    # The audit log has the story, without any secret.
    async with session_factory() as session:
        events = list(
            await session.scalars(
                select(SecurityAuditEvent).order_by(SecurityAuditEvent.created_at)
            )
        )
        hashes = list(await session.scalars(select(UserSession.token_hash)))
        hashes += list(await session.scalars(select(UserPasswordCredential.password_hash)))
    assert [event.action for event in events] == [
        "user.created",
        "user.created",
        "user.created",
        "auth.login",
        "auth.login",
        "auth.login",
        "organization.created",
        "organization.member_added",
        "organization.member_added",
        "investigation.collaborator_added",
        "auth.logout_all",
    ]
    dumped = json.dumps([[event.action, event.resource_type, event.details] for event in events])
    for secret in [TEST_PASSWORD, OTHER_PASSWORD, analyst_token, *hashes]:
        assert secret not in dumped


async def test_auth_disabled_keeps_the_old_behavior(client: httpx.AsyncClient) -> None:
    created = await client.post("/investigations", json={"title": "Floods"})
    listed = await client.get("/investigations")
    organizations = await client.get("/organizations")
    sources = await client.get("/sources")

    assert created.status_code == 201, created.text
    assert created.json()["organization_id"] is None
    assert listed.json()["total"] == 1
    assert organizations.status_code == 503
    assert sources.status_code == 200
