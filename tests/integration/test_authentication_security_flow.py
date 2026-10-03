"""End-to-end coverage for login throttling and password/session safety."""

import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from password_helpers import OTHER_PASSWORD, TEST_PASSWORD
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.users.credential import UserPasswordCredential
from signalscope.domain.users.login_throttle import login_identifier
from signalscope.domain.users.session import UserSession

pytestmark = pytest.mark.anyio


async def test_administrator_recovers_a_throttled_login_without_leaking_secrets(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await create_account(session_factory, "admin@example.org", system_admin=True)
    analyst = await create_account(session_factory, "analyst@example.org")
    await create_account(session_factory, "observer@example.org")
    admin_token = await login(auth_client, "admin@example.org")
    admin = bearer(admin_token)
    observer = bearer(await login(auth_client, "observer@example.org"))

    initial_token = await login(auth_client, "analyst@example.org")
    assert (
        await auth_client.post("/auth/logout", headers=bearer(initial_token))
    ).status_code == 204

    deactivated = await auth_client.patch(
        f"/admin/users/{analyst.id}/status", json={"is_active": False}, headers=admin
    )
    inactive = await auth_client.post(
        "/auth/login", json={"email": "analyst@example.org", "password": TEST_PASSWORD}
    )
    unknown = await auth_client.post(
        "/auth/login", json={"email": "missing@example.org", "password": TEST_PASSWORD}
    )
    assert deactivated.status_code == 200
    assert inactive.status_code == unknown.status_code == 401
    assert inactive.json() == unknown.json()
    assert (
        await auth_client.patch(
            f"/admin/users/{analyst.id}/status", json={"is_active": True}, headers=admin
        )
    ).status_code == 200

    failures = [
        await auth_client.post(
            "/auth/login", json={"email": "analyst@example.org", "password": OTHER_PASSWORD}
        )
        for _ in range(10)
    ]
    blocked = await auth_client.post(
        "/auth/login", json={"email": "analyst@example.org", "password": TEST_PASSWORD}
    )
    assert all(response.status_code == 401 for response in [*failures, blocked])
    assert all(response.json() == blocked.json() for response in failures)

    identifier = login_identifier("analyst@example.org")
    denied = await auth_client.get("/admin/auth/throttles", headers=observer)
    listed = await auth_client.get("/admin/auth/throttles", headers=admin)
    assert denied.status_code == 403
    assert listed.status_code == 200
    assert identifier in [item["identifier"] for item in listed.json()["items"]]
    assert (
        await auth_client.delete(f"/admin/auth/throttles/{identifier}", headers=admin)
    ).status_code == 204

    current_token = await login(auth_client, "analyst@example.org")
    other_token = await login(auth_client, "analyst@example.org")
    changed = await auth_client.post(
        "/auth/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": OTHER_PASSWORD},
        headers=bearer(current_token),
    )
    assert changed.status_code == 204
    assert (await auth_client.get("/auth/me", headers=bearer(current_token))).status_code == 200
    assert (await auth_client.get("/auth/me", headers=bearer(other_token))).status_code == 401
    old_password = await auth_client.post(
        "/auth/login", json={"email": "analyst@example.org", "password": TEST_PASSWORD}
    )
    assert old_password.status_code == 401
    final_token = await login(auth_client, "analyst@example.org", OTHER_PASSWORD)

    responses = [deactivated, inactive, unknown, *failures, blocked, denied, listed, changed]
    async with session_factory() as session:
        events = list(await session.scalars(select(SecurityAuditEvent)))
        secrets = list(await session.scalars(select(UserPasswordCredential.password_hash)))
        secrets += list(await session.scalars(select(UserSession.token_hash)))
    audit_text = json.dumps(
        [[event.action, event.resource_type, event.details] for event in events]
    )
    response_text = "".join(response.text for response in responses)
    for secret in [
        TEST_PASSWORD,
        OTHER_PASSWORD,
        admin_token,
        current_token,
        other_token,
        final_token,
        f"Bearer {admin_token}",
        *secrets,
    ]:
        assert secret not in audit_text
        assert secret not in response_text
