from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from password_helpers import TEST_PASSWORD, fast_hasher
from signalscope.core.errors import UnauthenticatedError
from signalscope.domain.users.authentication import AuthenticationService
from signalscope.domain.users.session import UserSession

pytestmark = pytest.mark.anyio

# Idle is above LAST_SEEN_INTERVAL (15 min) so active use refreshes last_seen.
MAX_AGE = 3600
IDLE = 1800
STEP = 1200


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)

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


async def login(session_factory: async_sessionmaker[AsyncSession], clock: Clock) -> str:
    async with session_factory() as session:
        await service(session, clock).create_user("ana@example.org", "Ana", TEST_PASSWORD)
    async with session_factory() as session:
        return (await service(session, clock).login("ana@example.org", TEST_PASSWORD)).token


async def test_fresh_session_resolves(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    clock = Clock()
    token = await login(session_factory, clock)
    async with session_factory() as session:
        resolved = await service(session, clock).resolve_session(token)
    assert resolved.user.email == "ana@example.org"


async def test_idle_timeout_invalidates_and_revokes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    clock = Clock()
    token = await login(session_factory, clock)
    clock.now += timedelta(seconds=IDLE + 1)

    async with session_factory() as session:
        with pytest.raises(UnauthenticatedError):
            await service(session, clock).resolve_session(token)

    async with session_factory() as session:
        stored = (await session.scalars(select(UserSession))).one()
    assert stored.revoked_at is not None


async def test_absolute_age_invalidates_even_with_activity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    clock = Clock()
    token = await login(session_factory, clock)

    # Stay active within the idle window until the absolute age is exceeded.
    elapsed = 0
    while elapsed < MAX_AGE:
        clock.now += timedelta(seconds=STEP)
        elapsed += STEP
        async with session_factory() as session:
            if elapsed >= MAX_AGE:
                with pytest.raises(UnauthenticatedError):
                    await service(session, clock).resolve_session(token)
            else:
                await service(session, clock).resolve_session(token)


async def test_activity_refreshes_idle_but_not_absolute(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    clock = Clock()
    token = await login(session_factory, clock)
    created = clock.now

    clock.now += timedelta(seconds=STEP)
    async with session_factory() as session:
        await service(session, clock).resolve_session(token)

    async with session_factory() as session:
        stored = (await session.scalars(select(UserSession))).one()
        # last_seen advanced; created_at and expires_at unchanged.
        assert stored.last_seen_at == clock.now
        assert stored.created_at == created
        assert stored.expires_at == created + timedelta(days=7)
