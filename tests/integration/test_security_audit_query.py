import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.core.errors import ForbiddenError, InvalidInputError, NotFoundError
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.audit.query import SecurityAuditQueryService
from signalscope.domain.organizations.membership import OrganizationRole
from signalscope.domain.organizations.service import OrganizationService
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio

DAY = datetime(2026, 9, 1, tzinfo=UTC)
TEST_ACTION = "test.event"


class World:
    users: dict[str, User]
    organizations: dict[str, uuid.UUID]


@pytest.fixture
async def world(session_factory: async_sessionmaker[AsyncSession]) -> World:
    """Two organizations, one user per role, and test events on three days."""
    found = World()
    found.users = {}
    for name in ("system", "owner", "admin", "member", "viewer", "other", "leaver"):
        found.users[name] = await create_account(
            session_factory, f"{name}@example.org", system_admin=name == "system"
        )
    users = found.users
    async with session_factory() as session:
        service = OrganizationService(session)
        harbour = await service.create(users["owner"], "Harbour", "harbour")
        river = await service.create(users["other"], "River", "river")
        for name in ("admin", "member", "viewer"):
            await service.add_member(
                users["owner"], harbour.id, users[name].id, OrganizationRole(name)
            )
    found.organizations = {"harbour": harbour.id, "river": river.id}
    async with session_factory() as session:
        for day, organization, actor, resource_type in [
            (0, "harbour", "owner", "organization"),
            (1, "harbour", "leaver", "investigation"),
            (2, "harbour", "admin", "investigation"),
            (1, "river", "other", "organization"),
            (2, None, "system", "user"),
        ]:
            session.add(
                SecurityAuditEvent(
                    actor_user_id=users[actor].id,
                    organization_id=None
                    if organization is None
                    else found.organizations[organization],
                    action=TEST_ACTION,
                    resource_type=resource_type,
                    resource_id=uuid.UUID(int=day + 1),
                    details={"role": "member"},
                    created_at=DAY + timedelta(days=day),
                )
            )
        await session.commit()
    return found


async def query(
    session_factory: async_sessionmaker[AsyncSession], actor: User, **filters: object
) -> tuple[list[tuple[str, str | None, int]], int]:
    """(resource type, actor email, day) for each test event found, and the total."""
    async with session_factory() as session:
        found, total = await SecurityAuditQueryService(session, actor).query(
            action=TEST_ACTION,
            **filters,  # type: ignore[arg-type]
        )
    return [
        (
            item.event.resource_type,
            None if item.actor is None else item.actor.email,
            (item.event.created_at - DAY).days,
        )
        for item in found
    ], total


async def test_system_admin_reads_everything(
    session_factory: async_sessionmaker[AsyncSession], world: World
) -> None:
    found, total = await query(session_factory, world.users["system"])

    assert total == 5
    assert [day for _, _, day in found] == [2, 2, 1, 1, 0]
    async with session_factory() as session:
        everything, all_total = await SecurityAuditQueryService(
            session, world.users["system"]
        ).query()
        stored = await session.scalar(select(func.count()).select_from(SecurityAuditEvent))
    assert all_total == stored and len(everything) == min(50, stored or 0)


@pytest.mark.parametrize("name", ["owner", "admin"])
async def test_organization_managers_read_their_organization(
    session_factory: async_sessionmaker[AsyncSession], world: World, name: str
) -> None:
    found, total = await query(
        session_factory, world.users[name], organization_id=world.organizations["harbour"]
    )

    assert total == 3
    assert [(kind, day) for kind, _, day in found] == [
        ("investigation", 2),
        ("investigation", 1),
        ("organization", 0),
    ]


async def test_access_is_limited(
    session_factory: async_sessionmaker[AsyncSession], world: World
) -> None:
    harbour = world.organizations["harbour"]
    for name in ("member", "viewer"):
        with pytest.raises(ForbiddenError):
            await query(session_factory, world.users[name], organization_id=harbour)
        with pytest.raises(ForbiddenError):
            await query(session_factory, world.users[name])
    with pytest.raises(NotFoundError):
        await query(
            session_factory, world.users["owner"], organization_id=world.organizations["river"]
        )
    with pytest.raises(NotFoundError):
        await query(session_factory, world.users["owner"], organization_id=uuid.uuid4())
    with pytest.raises(InvalidInputError, match="organization_id is required"):
        await query(session_factory, world.users["owner"])


async def test_filters_dates_and_pages(
    session_factory: async_sessionmaker[AsyncSession], world: World
) -> None:
    system = world.users["system"]

    by_actor = await query(session_factory, system, actor_user_id=world.users["admin"].id)
    by_type = await query(session_factory, system, resource_type="organization")
    by_resource = await query(session_factory, system, resource_id=uuid.UUID(int=1))
    by_dates = await query(
        session_factory,
        system,
        created_from=DAY + timedelta(days=1),
        created_to=DAY + timedelta(days=2),
    )
    page = await query(session_factory, system, limit=2, offset=2)

    assert by_actor == ([("investigation", "admin@example.org", 2)], 1)
    assert [day for _, _, day in by_type[0]] == [1, 0]
    assert by_resource[1] == 1
    assert (sorted(kind for kind, _, _ in by_dates[0]), by_dates[1]) == (
        ["investigation", "organization"],
        2,
    )
    assert ([day for _, _, day in page[0]], page[1]) == ([1, 1], 5)
    with pytest.raises(InvalidInputError):
        await query(session_factory, system, created_from=DAY, created_to=DAY - timedelta(days=1))


async def test_deleted_actor(
    session_factory: async_sessionmaker[AsyncSession], world: World
) -> None:
    async with session_factory() as session:
        await session.execute(delete(User).where(User.id == world.users["leaver"].id))
        await session.commit()

    found, _ = await query(
        session_factory,
        world.users["system"],
        created_from=DAY + timedelta(days=1),
        created_to=DAY + timedelta(days=2),
    )

    assert ("investigation", None, 1) in found
