import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from password_helpers import TEST_PASSWORD
from signalscope.core.errors import ConflictError
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.users.administration import UserAdministrationService
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio


async def set_status(
    client: httpx.AsyncClient, headers: dict[str, str], user_id: uuid.UUID, active: bool
) -> httpx.Response:
    return await client.patch(
        f"/admin/users/{user_id}/status", json={"is_active": active}, headers=headers
    )


async def test_deactivate_and_reactivate(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    root_user = await create_account(session_factory, "root@example.org", system_admin=True)
    ana = await create_account(session_factory, "ana@example.org")
    root = bearer(await login(auth_client, "root@example.org"))
    old_sessions = [bearer(await login(auth_client, "ana@example.org")) for _ in range(2)]

    deactivated = await set_status(auth_client, root, ana.id, False)

    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["is_active"] is False
    for headers in old_sessions:
        assert (await auth_client.get("/auth/me", headers=headers)).status_code == 401
    refused = await auth_client.post(
        "/auth/login", json={"email": "ana@example.org", "password": TEST_PASSWORD}
    )
    assert refused.status_code == 401
    assert refused.json()["error"]["message"] == "Email or password is not correct."
    again = await set_status(auth_client, root, ana.id, False)
    assert again.status_code == 200

    reactivated = await set_status(auth_client, root, ana.id, True)

    assert reactivated.json()["is_active"] is True
    for headers in old_sessions:
        assert (await auth_client.get("/auth/me", headers=headers)).status_code == 401
    fresh = bearer(await login(auth_client, "ana@example.org"))
    assert (await auth_client.get("/auth/me", headers=fresh)).status_code == 200

    async with session_factory() as session:
        events = list(
            await session.scalars(
                select(SecurityAuditEvent)
                .where(SecurityAuditEvent.resource_id == ana.id)
                .order_by(SecurityAuditEvent.created_at)
            )
        )
    lifecycle = [
        event for event in events if event.action.startswith("user.") and event.actor_user_id
    ]
    assert [(event.action, event.details) for event in lifecycle] == [
        ("user.deactivated", {"revoked_sessions": 2}),
        ("user.reactivated", {}),
    ]
    assert all(event.actor_user_id == root_user.id for event in lifecycle)


async def test_errors(
    auth_client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    root_user = await create_account(session_factory, "root@example.org", system_admin=True)
    ana = await create_account(session_factory, "ana@example.org")
    root = bearer(await login(auth_client, "root@example.org"))
    user = bearer(await login(auth_client, "ana@example.org"))

    last_admin = await set_status(auth_client, root, root_user.id, False)
    by_user = await set_status(auth_client, user, root_user.id, False)
    unknown = await set_status(auth_client, root, uuid.uuid4(), False)
    bad_body = await auth_client.patch(
        f"/admin/users/{ana.id}/status", json={"is_active": "maybe"}, headers=root
    )

    assert last_admin.status_code == 409
    assert last_admin.json()["error"]["message"] == (
        "There must be at least one active system admin."
    )
    assert (await auth_client.get("/auth/me", headers=root)).status_code == 200
    assert (by_user.status_code, unknown.status_code, bad_body.status_code) == (403, 404, 422)


async def test_an_admin_may_step_down_while_another_remains(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await create_account(session_factory, "first@example.org", system_admin=True)
    await create_account(session_factory, "second@example.org", system_admin=True)

    async with session_factory() as session:
        stepped_down = await UserAdministrationService(session, first).deactivate_user(first.id)

    assert stepped_down.is_active is False


async def test_two_admins_deactivated_at_once_keep_one(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await create_account(session_factory, "first@example.org", system_admin=True)
    second = await create_account(session_factory, "second@example.org", system_admin=True)

    async def deactivate(actor: User, target: User) -> bool:
        async with session_factory() as session:
            try:
                await UserAdministrationService(session, actor).deactivate_user(target.id)
            except ConflictError:
                return False
            return True

    results = await asyncio.gather(deactivate(first, second), deactivate(second, first))

    assert sorted(results) == [False, True]
    async with session_factory() as session:
        active_admins = await session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.is_system_admin.is_(True), User.is_active.is_(True))
        )
    assert active_admins == 1
