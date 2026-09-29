from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from password_helpers import OTHER_PASSWORD, TEST_PASSWORD
from signalscope.domain.users.model import User
from signalscope.domain.users.session import UserSession

pytestmark = pytest.mark.anyio


async def test_login_and_me(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user = await create_account(session_factory, "Ana@Example.org", display_name="Ana Silva")

    response = await auth_client.post(
        "/auth/login", json={"email": "ana@example.org", "password": TEST_PASSWORD}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"] == {
        "id": str(user.id),
        "email": "Ana@Example.org",
        "display_name": "Ana Silva",
        "is_active": True,
        "is_system_admin": False,
    }
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(days=6) < expires - datetime.now(UTC) <= timedelta(days=7)
    assert "hash" not in response.text and TEST_PASSWORD not in response.text

    me = await auth_client.get("/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["user"]["id"] == str(user.id)


async def test_failed_logins_share_one_answer(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await create_account(session_factory, "ana@example.org")

    wrong = await auth_client.post(
        "/auth/login", json={"email": "ana@example.org", "password": OTHER_PASSWORD}
    )
    unknown = await auth_client.post(
        "/auth/login", json={"email": "bob@example.org", "password": OTHER_PASSWORD}
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"]["message"] == "Email or password is not correct."
    assert OTHER_PASSWORD not in wrong.text


async def test_inactive_account(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user = await create_account(session_factory, "ana@example.org")
    token = await login(auth_client, "ana@example.org")
    async with session_factory() as session:
        await session.execute(update(User).where(User.id == user.id).values(is_active=False))
        await session.commit()

    me = await auth_client.get("/auth/me", headers=bearer(token))
    again = await auth_client.post(
        "/auth/login", json={"email": "ana@example.org", "password": TEST_PASSWORD}
    )

    assert (me.status_code, again.status_code) == (401, 401)


async def test_bad_and_expired_tokens(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await create_account(session_factory, "ana@example.org")
    token = await login(auth_client, "ana@example.org")
    async with session_factory() as session:
        await session.execute(
            update(UserSession).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()

    for headers in ({}, bearer("not-a-real-token"), bearer(token)):
        response = await auth_client.get("/auth/me", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Authentication is required."


async def test_logout(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await create_account(session_factory, "ana@example.org")
    token = await login(auth_client, "ana@example.org")
    other = await login(auth_client, "ana@example.org")

    logout = await auth_client.post("/auth/logout", headers=bearer(token))

    assert logout.status_code == 204
    assert (await auth_client.get("/auth/me", headers=bearer(token))).status_code == 401
    # Only that session ends.
    assert (await auth_client.get("/auth/me", headers=bearer(other))).status_code == 200
