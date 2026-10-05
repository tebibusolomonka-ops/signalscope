import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from password_helpers import TEST_PASSWORD, fast_hasher
from signalscope.core.errors import UnauthenticatedError
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.users.authentication import AuthenticationService
from signalscope.domain.users.session import UserSession

pytestmark = pytest.mark.anyio

MAX_AGE = 3600
IDLE = 1800
STEP = 1200


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 4, 1, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def service(session: AsyncSession, clock: Clock) -> AuthenticationService:
    return AuthenticationService(
        session,
        fast_hasher(),
        clock,
        session_days=7,
        session_max_age_seconds=MAX_AGE,
        session_idle_seconds=IDLE,
    )


async def test_session_security_flow_and_no_secret_leak(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    clock = Clock()
    async with session_factory() as session:
        await service(session, clock).create_user("ana@example.org", "Ana", TEST_PASSWORD)

    # Two devices sign in.
    async with session_factory() as session:
        device_a = await service(session, clock).login("ana@example.org", TEST_PASSWORD)
    async with session_factory() as session:
        device_b = await service(session, clock).login("ana@example.org", TEST_PASSWORD)

    async with session_factory() as session:
        listed = await service(session, clock).list_sessions(device_a.user.id)
    assert len(listed) == 2

    # Device A revokes device B; B can no longer authenticate.
    async with session_factory() as session:
        await service(session, clock).revoke_user_session(device_a.user.id, device_b.session_id)
    async with session_factory() as session:
        with pytest.raises(UnauthenticatedError):
            await service(session, clock).resolve_session(device_b.token)

    # A third session idle-expires.
    async with session_factory() as session:
        device_c = await service(session, clock).login("ana@example.org", TEST_PASSWORD)
    clock.now += timedelta(seconds=IDLE + 1)
    async with session_factory() as session:
        with pytest.raises(UnauthenticatedError):
            await service(session, clock).resolve_session(device_c.token)

    # Device A stays active across refreshes until the absolute age is exceeded.
    clock.now = Clock().now
    elapsed = 0
    while elapsed < MAX_AGE:
        clock.now += timedelta(seconds=STEP)
        elapsed += STEP
        async with session_factory() as session:
            if elapsed >= MAX_AGE:
                with pytest.raises(UnauthenticatedError):
                    await service(session, clock).resolve_session(device_a.token)
            else:
                await service(session, clock).resolve_session(device_a.token)

    # No audit event stored a token, token hash or password.
    async with session_factory() as session:
        events = list(await session.scalars(select(SecurityAuditEvent)))
        hashes = list(await session.scalars(select(UserSession.token_hash)))
    blob = json.dumps([event.details for event in events])
    for secret in [device_a.token, device_b.token, device_c.token, TEST_PASSWORD, *hashes]:
        assert secret not in blob


async def test_password_change_revokes_other_sessions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    clock = Clock()
    async with session_factory() as session:
        await service(session, clock).create_user("ben@example.org", "Ben", TEST_PASSWORD)
    async with session_factory() as session:
        keep = await service(session, clock).login("ben@example.org", TEST_PASSWORD)
    async with session_factory() as session:
        other = await service(session, clock).login("ben@example.org", TEST_PASSWORD)

    async with session_factory() as session:
        current = await service(session, clock).resolve_session(keep.token)
        await service(session, clock).change_password(
            current, TEST_PASSWORD, "a brand new password"
        )

    async with session_factory() as session:
        svc = service(session, clock)
        assert (await svc.resolve_session(keep.token)).user.email == "ben@example.org"
        with pytest.raises(UnauthenticatedError):
            await svc.resolve_session(other.token)
