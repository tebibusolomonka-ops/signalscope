import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from signalscope.domain.users.session import UserSession

pytestmark = pytest.mark.anyio


async def test_list_sessions(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await create_account(session_factory, "ana@example.org")
    first = await login(auth_client, "ana@example.org")
    second = await login(auth_client, "ana@example.org")

    response = await auth_client.get("/auth/sessions", headers=bearer(second))

    assert response.status_code == 200, response.text
    sessions = response.json()
    assert len(sessions) == 2
    assert set(sessions[0]) == {
        "session_id",
        "created_at",
        "expires_at",
        "last_seen_at",
        "revoked",
        "revoked_at",
        "current_session",
    }
    assert [item["current_session"] for item in sessions] == [True, False]
    assert not any(item["revoked"] for item in sessions)
    async with session_factory() as session:
        hashes = list(await session.scalars(select(UserSession.token_hash)))
    for secret in [first, second, *hashes]:
        assert secret not in response.text


async def test_revoke_one_session(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await create_account(session_factory, "ana@example.org")
    await create_account(session_factory, "ben@example.org")
    phone = await login(auth_client, "ana@example.org")
    laptop = await login(auth_client, "ana@example.org")
    other = await login(auth_client, "ben@example.org")
    me = await auth_client.get("/auth/me", headers=bearer(phone))
    phone_id = me.json()["session_id"]

    by_other = await auth_client.delete(f"/auth/sessions/{phone_id}", headers=bearer(other))
    unknown = await auth_client.delete(f"/auth/sessions/{uuid.uuid4()}", headers=bearer(laptop))
    revoked = await auth_client.delete(f"/auth/sessions/{phone_id}", headers=bearer(laptop))
    again = await auth_client.delete(f"/auth/sessions/{phone_id}", headers=bearer(laptop))

    assert by_other.status_code == 404
    assert unknown.status_code == 404
    assert revoked.status_code == 204
    assert again.status_code == 204
    assert (await auth_client.get("/auth/me", headers=bearer(phone))).status_code == 401
    assert (await auth_client.get("/auth/me", headers=bearer(laptop))).status_code == 200
    listed = (await auth_client.get("/auth/sessions", headers=bearer(laptop))).json()
    assert {item["session_id"]: item["revoked"] for item in listed}[phone_id] is True


async def test_logout_all(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await create_account(session_factory, "ana@example.org")
    await create_account(session_factory, "ben@example.org")
    tokens = [await login(auth_client, "ana@example.org") for _ in range(3)]
    other = await login(auth_client, "ben@example.org")

    response = await auth_client.post("/auth/logout-all", headers=bearer(tokens[0]))

    assert response.status_code == 204
    for token in tokens:
        assert (await auth_client.get("/auth/me", headers=bearer(token))).status_code == 401
    assert (await auth_client.get("/auth/me", headers=bearer(other))).status_code == 200
