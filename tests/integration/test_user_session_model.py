import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.users.model import User
from signalscope.domain.users.session import UserSession

pytestmark = pytest.mark.anyio

EXPIRES = datetime(2030, 1, 1, tzinfo=UTC)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_user(session_factory: async_sessionmaker[AsyncSession]) -> User:
    async with session_factory() as session:
        user = User(email="ana@example.org", normalized_email="ana@example.org", display_name="Ana")
        session.add(user)
        await session.commit()
        return user


async def test_session_is_stored(session_factory: async_sessionmaker[AsyncSession]) -> None:
    user = await create_user(session_factory)
    async with session_factory() as session:
        stored = UserSession(user_id=user.id, token_hash=token_hash("a"), expires_at=EXPIRES)
        session.add(stored)
        await session.commit()

    async with session_factory() as session:
        found = await session.get(UserSession, stored.id)
    assert found is not None
    assert (found.expires_at, found.revoked_at) == (EXPIRES, None)
    assert found.expires_at.utcoffset() == timedelta(0)
    assert found.created_at is not None and found.last_seen_at is not None


@pytest.mark.parametrize(
    "value",
    ["A" * 64, "0" * 63, "g" * 64, "raw-token"],
    ids=["upper case", "short", "not hex", "raw token"],
)
async def test_only_sha256_hex_is_accepted(
    session_factory: async_sessionmaker[AsyncSession], value: str
) -> None:
    user = await create_user(session_factory)
    async with session_factory() as session:
        session.add(UserSession(user_id=user.id, token_hash=value, expires_at=EXPIRES))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_token_hash_is_unique(session_factory: async_sessionmaker[AsyncSession]) -> None:
    user = await create_user(session_factory)
    async with session_factory() as session:
        session.add(UserSession(user_id=user.id, token_hash=token_hash("a"), expires_at=EXPIRES))
        await session.commit()

    async with session_factory() as session:
        session.add(UserSession(user_id=user.id, token_hash=token_hash("a"), expires_at=EXPIRES))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_deleting_the_user_deletes_sessions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user = await create_user(session_factory)
    async with session_factory() as session:
        session.add(UserSession(user_id=user.id, token_hash=token_hash("a"), expires_at=EXPIRES))
        await session.commit()
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()
        assert list(await session.scalars(select(UserSession))) == []
