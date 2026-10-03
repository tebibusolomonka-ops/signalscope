import io
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import bearer, create_account, login
from signalscope.cli import clear_login_throttle
from signalscope.core.settings import Settings
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.users.login_throttle import login_identifier
from signalscope.domain.users.throttle import AuthenticationThrottle

pytestmark = pytest.mark.anyio


async def _add_throttle(
    session_factory: async_sessionmaker[AsyncSession], email: str, failures: int
) -> str:
    identifier = login_identifier(email)
    async with session_factory() as session:
        session.add(
            AuthenticationThrottle(
                identifier=identifier,
                failure_count=failures,
                window_started_at=datetime.now(UTC),
            )
        )
        await session.commit()
    return identifier


async def test_admin_lists_pages_and_clears_with_audit(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await create_account(session_factory, "root@example.org", system_admin=True)
    root = bearer(await login(auth_client, "root@example.org"))
    identifiers = sorted(
        [
            await _add_throttle(session_factory, "one@example.org", 2),
            await _add_throttle(session_factory, "two@example.org", 3),
        ]
    )

    page = await auth_client.get("/admin/auth/throttles?limit=1&offset=1", headers=root)
    cleared = await auth_client.delete(f"/admin/auth/throttles/{identifiers[0]}", headers=root)
    unknown = await auth_client.delete(f"/admin/auth/throttles/{'f' * 64}", headers=root)

    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert len(page.json()["items"]) == 1
    assert cleared.status_code == 204
    assert unknown.status_code == 404
    async with session_factory() as session:
        assert await session.get(AuthenticationThrottle, identifiers[0]) is None
        actions = list(await session.scalars(select(SecurityAuditEvent.action)))
    assert "auth.login_throttle_cleared" in actions


async def test_normal_user_is_denied(
    auth_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await create_account(session_factory, "user@example.org")
    headers = bearer(await login(auth_client, "user@example.org"))
    response = await auth_client.get("/admin/auth/throttles", headers=headers)
    assert response.status_code == 403


async def test_local_command_clears_without_disclosing_identifier(
    test_database_settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    identifier = await _add_throttle(session_factory, "command@example.org", 4)
    output = io.StringIO()

    result = await clear_login_throttle(identifier, test_database_settings, out=output)

    assert result == 0
    assert output.getvalue() == "Login throttle cleared.\n"
    assert identifier not in output.getvalue()
