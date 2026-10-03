import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from password_helpers import OTHER_PASSWORD, TEST_PASSWORD, fast_hasher
from signalscope.core.errors import ConflictError, InvalidInputError, UnauthenticatedError
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.users.authentication import (
    INVALID_CREDENTIALS,
    AuthenticationService,
    InvalidCredentialsError,
)
from signalscope.domain.users.credential import UserPasswordCredential
from signalscope.domain.users.model import User
from signalscope.domain.users.session import UserSession

pytestmark = pytest.mark.anyio


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


def service(session: AsyncSession, clock: Clock | None = None) -> AuthenticationService:
    return AuthenticationService(session, fast_hasher(), clock or Clock(), session_days=7)


async def create_user(
    session_factory: async_sessionmaker[AsyncSession],
    email: str = "Ana@Example.org",
    **options: bool,
) -> User:
    async with session_factory() as session:
        return await service(session).create_user(email, " Ana Silva ", TEST_PASSWORD, **options)


async def test_create_user(session_factory: async_sessionmaker[AsyncSession]) -> None:
    user = await create_user(session_factory, is_system_admin=True)

    assert (user.email, user.normalized_email, user.display_name) == (
        "Ana@Example.org",
        "ana@example.org",
        "Ana Silva",
    )
    assert (user.is_active, user.is_system_admin) == (True, True)
    async with session_factory() as session:
        credential = await session.get(UserPasswordCredential, user.id)
    assert credential is not None
    assert credential.password_hash.startswith("$argon2id$")
    assert TEST_PASSWORD not in credential.password_hash


async def test_duplicate_email_in_any_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await create_user(session_factory)

    with pytest.raises(ConflictError, match="already exists"):
        await create_user(session_factory, "ANA@example.org")
    async with session_factory() as session:
        assert len(list(await session.scalars(select(User)))) == 1


@pytest.mark.parametrize(
    ("email", "name", "password"),
    [
        ("not an email", "Ana", TEST_PASSWORD),
        ("a@b.org", " ", TEST_PASSWORD),
        ("a@b.org", "Ana", "short"),
    ],
    ids=["bad email", "blank name", "short password"],
)
async def test_bad_account_details_create_nothing(
    session_factory: async_sessionmaker[AsyncSession], email: str, name: str, password: str
) -> None:
    async with session_factory() as session:
        with pytest.raises(InvalidInputError):
            await service(session).create_user(email, name, password)
        assert list(await session.scalars(select(User))) == []


async def test_login_and_resolve(
    session_factory: async_sessionmaker[AsyncSession], clock: Clock
) -> None:
    user = await create_user(session_factory)

    async with session_factory() as session:
        new = await service(session, clock).login(" ANA@example.org ", TEST_PASSWORD)
    async with session_factory() as session:
        resolved = await service(session, clock).resolve_session(new.token)

    assert new.user.id == user.id
    assert new.expires_at == clock.now + timedelta(days=7)
    assert (resolved.user.id, resolved.session.id) == (user.id, new.session_id)


async def test_only_the_token_hash_is_stored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await create_user(session_factory)
    async with session_factory() as session:
        new = await service(session).login("ana@example.org", TEST_PASSWORD)

    async with session_factory() as session:
        stored = await session.get(UserSession, new.session_id)
    assert stored is not None
    assert stored.token_hash == hashlib.sha256(new.token.encode()).hexdigest()
    assert stored.token_hash != new.token
    assert len(new.token) >= 40


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("ana@example.org", OTHER_PASSWORD),
        ("bob@example.org", TEST_PASSWORD),
        ("bad", TEST_PASSWORD),
    ],
    ids=["wrong password", "unknown email", "not an email"],
)
async def test_failed_logins_look_the_same(
    session_factory: async_sessionmaker[AsyncSession], email: str, password: str
) -> None:
    await create_user(session_factory)

    async with session_factory() as session:
        with pytest.raises(InvalidCredentialsError) as error:
            await service(session).login(email, password)
        assert list(await session.scalars(select(UserSession))) == []

    assert str(error.value) == INVALID_CREDENTIALS


@pytest.mark.parametrize(
    ("email", "password", "reason"),
    [
        ("ana@example.org", OTHER_PASSWORD, "invalid_credentials"),
        ("missing@example.org", TEST_PASSWORD, "invalid_credentials"),
    ],
)
async def test_failed_login_audit_is_safe(
    session_factory: async_sessionmaker[AsyncSession],
    email: str,
    password: str,
    reason: str,
) -> None:
    await create_user(session_factory)
    async with session_factory() as session:
        with pytest.raises(InvalidCredentialsError, match=INVALID_CREDENTIALS):
            await service(session).login(email, password)
    async with session_factory() as session:
        event = (
            await session.scalars(
                select(SecurityAuditEvent).where(
                    SecurityAuditEvent.action == "authentication_login_failed"
                )
            )
        ).one()
    assert event.details == {"reason": reason}
    encoded = str(event.details).lower()
    assert password.lower() not in encoded
    assert all(word not in encoded for word in ("password_hash", "token", "authorization"))


async def test_inactive_user(session_factory: async_sessionmaker[AsyncSession]) -> None:
    user = await create_user(session_factory)
    async with session_factory() as session:
        new = await service(session).login("ana@example.org", TEST_PASSWORD)
        await session.execute(update(User).where(User.id == user.id).values(is_active=False))
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(InvalidCredentialsError, match=INVALID_CREDENTIALS):
            await service(session).login("ana@example.org", TEST_PASSWORD)
        with pytest.raises(UnauthenticatedError):
            await service(session).resolve_session(new.token)
    async with session_factory() as session:
        event = (
            await session.scalars(
                select(SecurityAuditEvent).where(
                    SecurityAuditEvent.action == "authentication_login_failed"
                )
            )
        ).one()
        assert event.details == {"reason": "inactive_user"}


async def test_expired_revoked_and_unknown_tokens(
    session_factory: async_sessionmaker[AsyncSession], clock: Clock
) -> None:
    await create_user(session_factory)
    async with session_factory() as session:
        expiring = await service(session, clock).login("ana@example.org", TEST_PASSWORD)
        revoked = await service(session, clock).login("ana@example.org", TEST_PASSWORD)
        await service(session, clock).revoke_session(revoked.session_id)
        # Revoking twice changes nothing.
        await service(session, clock).revoke_session(revoked.session_id)

    clock.now += timedelta(days=7)
    async with session_factory() as session:
        for token in (expiring.token, revoked.token, "not-a-token"):
            with pytest.raises(UnauthenticatedError):
                await service(session, clock).resolve_session(token)


async def test_last_seen_is_written_at_most_every_15_minutes(
    session_factory: async_sessionmaker[AsyncSession], clock: Clock
) -> None:
    await create_user(session_factory)
    async with session_factory() as session:
        new = await service(session, clock).login("ana@example.org", TEST_PASSWORD)
    started = clock.now

    clock.now = started + timedelta(minutes=5)
    async with session_factory() as session:
        await service(session, clock).resolve_session(new.token)
    async with session_factory() as session:
        stored = await session.get(UserSession, new.session_id)
        assert stored is not None and stored.last_seen_at == started

    clock.now = started + timedelta(minutes=20)
    async with session_factory() as session:
        await service(session, clock).resolve_session(new.token)
    async with session_factory() as session:
        stored = await session.get(UserSession, new.session_id)
        assert stored is not None and stored.last_seen_at == clock.now
