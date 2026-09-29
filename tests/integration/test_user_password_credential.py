import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from password_helpers import TEST_PASSWORD, fast_hasher
from signalscope.domain.users.credential import UserPasswordCredential
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio


async def create_user(session_factory: async_sessionmaker[AsyncSession]) -> User:
    async with session_factory() as session:
        user = User(email="ana@example.org", normalized_email="ana@example.org", display_name="Ana")
        session.add(user)
        await session.commit()
        return user


async def test_credential_is_stored_with_timestamps(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user = await create_user(session_factory)
    password_hash = fast_hasher().hash_password(TEST_PASSWORD)
    async with session_factory() as session:
        session.add(UserPasswordCredential(user_id=user.id, password_hash=password_hash))
        await session.commit()

    async with session_factory() as session:
        stored = await session.get(UserPasswordCredential, user.id)
    assert stored is not None
    assert stored.password_hash == password_hash
    assert stored.password_changed_at is not None and stored.created_at is not None


async def test_one_credential_per_user(session_factory: async_sessionmaker[AsyncSession]) -> None:
    user = await create_user(session_factory)
    async with session_factory() as session:
        session.add(UserPasswordCredential(user_id=user.id, password_hash="$argon2id$first"))
        await session.commit()

    async with session_factory() as session:
        session.add(UserPasswordCredential(user_id=user.id, password_hash="$argon2id$second"))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_deleting_the_user_deletes_the_credential(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user = await create_user(session_factory)
    async with session_factory() as session:
        session.add(UserPasswordCredential(user_id=user.id, password_hash="$argon2id$hash"))
        await session.commit()

    async with session_factory() as session:
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()
        assert list(await session.scalars(select(UserPasswordCredential))) == []
