import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.users.email import normalize_email
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio


def user(email: str, display_name: str = "Ana Silva") -> User:
    return User(
        email=email.strip(), normalized_email=normalize_email(email), display_name=display_name
    )


async def test_defaults_and_timestamps(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        created = user("Ana@Example.org")
        session.add(created)
        await session.commit()

    async with session_factory() as session:
        stored = await session.get(User, created.id)
    assert stored is not None
    assert (stored.email, stored.normalized_email, stored.display_name) == (
        "Ana@Example.org",
        "ana@example.org",
        "Ana Silva",
    )
    assert (stored.is_active, stored.is_system_admin) == (True, False)
    assert stored.created_at is not None and stored.updated_at is not None


async def test_email_is_unique_in_any_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(user("ana@example.org"))
        await session.commit()

    async with session_factory() as session:
        session.add(user("  ANA@EXAMPLE.ORG "))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_blank_display_name_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(user("ana@example.org", display_name=" "))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_display_name_length_limit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(user("ana@example.org", display_name="x" * 201))
        with pytest.raises(DBAPIError):
            await session.commit()
