import uuid
from typing import Any

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from password_helpers import OTHER_PASSWORD, fast_hasher
from signalscope.core.errors import ConflictError, ForbiddenError, NotFoundError
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.users.administration import UserAdministrationService
from signalscope.domain.users.authentication import AuthenticationService
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio


@pytest.fixture
async def people(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, User]:
    found = {"root": await create_account(session_factory, "root@example.org", system_admin=True)}
    found["ana"] = await create_account(
        session_factory, "ana@example.org", display_name="Ana Silva"
    )
    found["ben"] = await create_account(session_factory, "Ben@Example.org", display_name="Ben Ode")
    found["ops"] = await create_account(
        session_factory, "ops@example.org", display_name="Night Ops", system_admin=True
    )
    return found


def admin(session: AsyncSession, actor: User) -> UserAdministrationService:
    return UserAdministrationService(session, actor, fast_hasher())


async def emails(
    session_factory: async_sessionmaker[AsyncSession], actor: User, **filters: Any
) -> tuple[list[str], int]:
    async with session_factory() as session:
        users, total = await admin(session, actor).list_users(**filters)
    return [user.email for user in users], total


async def test_list_and_filters(
    session_factory: async_sessionmaker[AsyncSession], people: dict[str, User]
) -> None:
    root = people["root"]
    async with session_factory() as session:
        ana = await session.get_one(User, people["ana"].id)
        ana.is_active = False
        await session.commit()

    everyone = ["root@example.org", "ana@example.org", "Ben@Example.org", "ops@example.org"]
    assert await emails(session_factory, root) == (everyone, 4)
    assert await emails(session_factory, root, is_active=False) == (["ana@example.org"], 1)
    assert await emails(session_factory, root, is_system_admin=True) == (
        ["root@example.org", "ops@example.org"],
        2,
    )
    assert await emails(session_factory, root, query="BEN@") == (["Ben@Example.org"], 1)
    assert await emails(session_factory, root, query="night") == (["ops@example.org"], 1)
    assert await emails(session_factory, root, query="%") == ([], 0)
    assert await emails(session_factory, root, limit=2, offset=1) == (everyone[1:3], 4)


async def test_only_active_system_admins(
    session_factory: async_sessionmaker[AsyncSession], people: dict[str, User]
) -> None:
    async with session_factory() as session:
        service = admin(session, people["ana"])
        with pytest.raises(ForbiddenError):
            await service.list_users()
        with pytest.raises(ForbiddenError):
            await service.get_user(people["root"].id)
        with pytest.raises(ForbiddenError):
            await service.create_user("new@example.org", "New", OTHER_PASSWORD)
        people["ops"].is_active = False
        with pytest.raises(ForbiddenError):
            await admin(session, people["ops"]).list_users()


async def test_get_user(
    session_factory: async_sessionmaker[AsyncSession], people: dict[str, User]
) -> None:
    async with session_factory() as session:
        service = admin(session, people["root"])
        found = await service.get_user(people["ana"].id)
        with pytest.raises(NotFoundError, match="User was not found"):
            await service.get_user(uuid.uuid4())

    assert found.display_name == "Ana Silva"


async def test_create_user(
    session_factory: async_sessionmaker[AsyncSession], people: dict[str, User]
) -> None:
    async with session_factory() as session:
        created = await admin(session, people["root"]).create_user(
            " Cleo@Example.org ", "Cleo", OTHER_PASSWORD, is_system_admin=True
        )
    async with session_factory() as session:
        with pytest.raises(ConflictError):
            await admin(session, people["root"]).create_user(
                "cleo@example.org", "Other", OTHER_PASSWORD
            )
    async with session_factory() as session:
        signed_in = await AuthenticationService(session, fast_hasher()).authenticate_password(
            "cleo@example.org", OTHER_PASSWORD
        )
        audit = await session.scalar(
            select(SecurityAuditEvent).where(SecurityAuditEvent.resource_id == created.id)
        )

    assert (created.email, created.is_system_admin, signed_in.id) == (
        "Cleo@Example.org",
        True,
        created.id,
    )
    assert audit is not None and audit.actor_user_id == people["root"].id
    columns = {attribute.key for attribute in inspect(User).column_attrs}
    assert not any("password" in name or "hash" in name or "token" in name for name in columns)
