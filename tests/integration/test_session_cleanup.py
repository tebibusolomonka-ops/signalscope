import io
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.cli import cleanup_auth_sessions
from signalscope.core.settings import Settings
from signalscope.domain.users.authentication import hash_token
from signalscope.domain.users.session import UserSession
from signalscope.domain.users.session_cleanup import SessionCleanupService

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def at(days: float) -> datetime:
    return NOW + timedelta(days=days)


async def add_sessions(
    session_factory: async_sessionmaker[AsyncSession],
    ends: dict[str, tuple[datetime, datetime | None]],
) -> dict[str, uuid.UUID]:
    """One session per name, with its expiry and revoked time."""
    user = await create_account(session_factory, "ana@example.org")
    ids = {}
    async with session_factory() as session:
        for name, (expires_at, revoked_at) in ends.items():
            stored = UserSession(
                user_id=user.id,
                token_hash=hash_token(secrets.token_urlsafe(32)),
                expires_at=expires_at,
                revoked_at=revoked_at,
                created_at=expires_at - timedelta(days=7),
                last_seen_at=expires_at - timedelta(days=7),
            )
            session.add(stored)
            await session.flush()
            ids[name] = stored.id
        await session.commit()
    return ids


async def remaining(
    session_factory: async_sessionmaker[AsyncSession], ids: dict[str, uuid.UUID]
) -> set[str]:
    async with session_factory() as session:
        found = set(await session.scalars(select(UserSession.id)))
    return {name for name, session_id in ids.items() if session_id in found}


async def test_only_old_ended_sessions_are_deleted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await add_sessions(
        session_factory,
        {
            "active": (at(3), None),
            "recently expired": (at(-10), None),
            "old expired": (at(-40), None),
            "recently revoked": (at(3), at(-1)),
            "old revoked": (at(-20), at(-35)),
            # Revoked recently, but it expired long ago.
            "revoked late": (at(-40), at(-2)),
        },
    )

    async with session_factory() as session:
        result = await SessionCleanupService(session, lambda: NOW).run(30, 100)

    assert (result.checked, result.deleted) == (3, 3)
    assert await remaining(session_factory, ids) == {
        "active",
        "recently expired",
        "recently revoked",
    }


async def test_limit(session_factory: async_sessionmaker[AsyncSession]) -> None:
    ids = await add_sessions(
        session_factory, {f"old {index}": (at(-40 - index), None) for index in range(5)}
    )

    async with session_factory() as session:
        first = await SessionCleanupService(session, lambda: NOW).run(30, 2)
    async with session_factory() as session:
        second = await SessionCleanupService(session, lambda: NOW).run(30, 10)
    async with session_factory() as session:
        third = await SessionCleanupService(session, lambda: NOW).run(30, 10)

    assert (first.deleted, second.deleted, third.deleted) == (2, 3, 0)
    assert await remaining(session_factory, ids) == set()


async def test_command(
    database_engine: AsyncEngine,
    migrated_database: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await add_sessions(session_factory, {"active": (at(3), None), "old": (at(-5), None)})
    settings = Settings(database_url=migrated_database.database_url, auth_session_retention_days=2)
    out, err = io.StringIO(), io.StringIO()

    code = await cleanup_auth_sessions(10, settings, out, err, clock=lambda: NOW)

    assert (code, out.getvalue(), err.getvalue()) == (0, "Checked: 1\nDeleted: 1\n", "")
    assert await remaining(session_factory, ids) == {"active"}
