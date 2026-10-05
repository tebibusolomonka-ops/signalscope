import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.users.model import User
from signalscope.domain.users.session import UserSession

pytestmark = pytest.mark.anyio


@pytest.fixture
async def setup(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> tuple[dict[str, str], User, list[str], User]:
    await create_account(session_factory, "root@example.org", system_admin=True)
    ana = await create_account(session_factory, "ana@example.org")
    ben = await create_account(session_factory, "ben@example.org")
    root = bearer(await login(auth_client, "root@example.org"))
    tokens = [await login(auth_client, "ana@example.org") for _ in range(3)]
    return root, ana, tokens, ben


async def test_list_and_revoke(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    setup: tuple[dict[str, str], User, list[str], User],
) -> None:
    root, ana, tokens, _ = setup
    sessions = f"/admin/users/{ana.id}/sessions"

    listed = await auth_client.get(sessions, headers=root)

    assert listed.status_code == 200, listed.text
    items = listed.json()
    assert len(items) == 3
    assert set(items[0]) == {
        "session_id",
        "created_at",
        "expires_at",
        "effective_expires_at",
        "last_seen_at",
        "revoked_at",
        "active",
    }
    assert all(item["active"] for item in items)
    async with session_factory() as session:
        hashes = list(await session.scalars(select(UserSession.token_hash)))
    for secret in [*tokens, *hashes]:
        assert secret not in listed.text

    newest = items[0]["session_id"]
    revoked = await auth_client.delete(f"{sessions}/{newest}", headers=root)
    assert revoked.status_code == 204
    assert (await auth_client.get("/auth/me", headers=bearer(tokens[-1]))).status_code == 401
    assert (await auth_client.get("/auth/me", headers=bearer(tokens[0]))).status_code == 200

    all_revoked = await auth_client.post(f"/admin/users/{ana.id}/revoke-sessions", headers=root)
    assert all_revoked.json() == {"revoked_sessions": 2}
    for token in tokens:
        assert (await auth_client.get("/auth/me", headers=bearer(token))).status_code == 401
    after = (await auth_client.get(sessions, headers=root)).json()
    assert not any(item["active"] for item in after)
    assert all(item["revoked_at"] for item in after)
    # The account itself stays active.
    assert await login(auth_client, "ana@example.org")

    async with session_factory() as session:
        events = list(
            await session.scalars(
                select(SecurityAuditEvent)
                .where(SecurityAuditEvent.action.startswith("admin."))
                .order_by(SecurityAuditEvent.created_at)
            )
        )
    assert [(event.action, event.details) for event in events] == [
        ("admin.session_revoked", {"user_id": str(ana.id)}),
        ("admin.sessions_revoked", {"revoked_sessions": 2}),
    ]


async def test_errors(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    setup: tuple[dict[str, str], User, list[str], User],
) -> None:
    root, ana, tokens, ben = setup
    ana_session = (await auth_client.get("/auth/me", headers=bearer(tokens[0]))).json()[
        "session_id"
    ]
    user = bearer(tokens[1])

    responses = {
        "wrong target": await auth_client.delete(
            f"/admin/users/{ben.id}/sessions/{ana_session}", headers=root
        ),
        "unknown session": await auth_client.delete(
            f"/admin/users/{ana.id}/sessions/{uuid.uuid4()}", headers=root
        ),
        "unknown user": await auth_client.get(
            f"/admin/users/{uuid.uuid4()}/sessions", headers=root
        ),
        "unknown user revoke": await auth_client.post(
            f"/admin/users/{uuid.uuid4()}/revoke-sessions", headers=root
        ),
        "normal user lists": await auth_client.get(f"/admin/users/{ana.id}/sessions", headers=user),
        "normal user revokes": await auth_client.post(
            f"/admin/users/{ben.id}/revoke-sessions", headers=user
        ),
    }

    assert {name: response.status_code for name, response in responses.items()} == {
        "wrong target": 404,
        "unknown session": 404,
        "unknown user": 404,
        "unknown user revoke": 404,
        "normal user lists": 403,
        "normal user revokes": 403,
    }
    assert (await auth_client.get("/auth/me", headers=bearer(tokens[0]))).status_code == 200
