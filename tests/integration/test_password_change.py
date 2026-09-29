import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from password_helpers import OTHER_PASSWORD, TEST_PASSWORD
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.users.credential import UserPasswordCredential
from signalscope.domain.users.session import UserSession

pytestmark = pytest.mark.anyio

NEW_PASSWORD = "a brand new long test password"


async def change(
    client: httpx.AsyncClient, headers: dict[str, str], current: str, new: str
) -> httpx.Response:
    return await client.post(
        "/auth/change-password",
        json={"current_password": current, "new_password": new},
        headers=headers,
    )


async def test_change_password(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user = await create_account(session_factory, "ana@example.org")
    current = bearer(await login(auth_client, "ana@example.org"))
    others = [bearer(await login(auth_client, "ana@example.org")) for _ in range(2)]
    async with session_factory() as session:
        before = await session.get_one(UserPasswordCredential, user.id)

    response = await change(auth_client, current, TEST_PASSWORD, NEW_PASSWORD)

    assert response.status_code == 204, response.text
    assert (await auth_client.get("/auth/me", headers=current)).status_code == 200
    for headers in others:
        assert (await auth_client.get("/auth/me", headers=headers)).status_code == 401
    assert await login(auth_client, "ana@example.org", NEW_PASSWORD)
    old = await auth_client.post(
        "/auth/login", json={"email": "ana@example.org", "password": TEST_PASSWORD}
    )
    assert old.status_code == 401

    async with session_factory() as session:
        after = await session.get_one(UserPasswordCredential, user.id)
        hashes = list(await session.scalars(select(UserSession.token_hash)))
        event = await session.scalar(
            select(SecurityAuditEvent).where(SecurityAuditEvent.action == "auth.password_changed")
        )
    assert after.password_hash != before.password_hash
    assert after.password_changed_at > before.password_changed_at
    assert event is not None
    assert (event.actor_user_id, event.details) == (user.id, {"revoked_sessions": 2})
    dumped = json.dumps([event.action, event.resource_type, event.details])
    secrets = [TEST_PASSWORD, NEW_PASSWORD, before.password_hash, after.password_hash, *hashes]
    for secret in secrets:
        assert secret not in dumped


async def test_refused_changes(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await create_account(session_factory, "ana@example.org")
    current = bearer(await login(auth_client, "ana@example.org"))
    other = bearer(await login(auth_client, "ana@example.org"))

    wrong = await change(auth_client, current, OTHER_PASSWORD, NEW_PASSWORD)
    too_short = await change(auth_client, current, TEST_PASSWORD, "short")
    too_long = await change(auth_client, current, TEST_PASSWORD, "x" * 1025)
    same = await change(auth_client, current, TEST_PASSWORD, TEST_PASSWORD)
    no_token = await auth_client.post(
        "/auth/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert wrong.status_code == 403
    assert wrong.json()["error"]["message"] == "The current password is not correct."
    assert too_short.status_code == 422
    assert "12 to 1024" in too_short.json()["error"]["message"]
    assert too_long.status_code == 422
    assert same.status_code == 422
    assert no_token.status_code == 401
    for response in (wrong, too_short, same):
        assert TEST_PASSWORD not in response.text and OTHER_PASSWORD not in response.text
    # Nothing changed: the old password and the other session still work.
    assert (await auth_client.get("/auth/me", headers=other)).status_code == 200
    assert await login(auth_client, "ana@example.org")
