import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.core.errors import ConflictError, ForbiddenError, InvalidInputError, NotFoundError
from signalscope.domain.organizations.membership import OrganizationMembership, OrganizationRole
from signalscope.domain.organizations.model import Organization
from signalscope.domain.organizations.service import OrganizationService
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio

Role = OrganizationRole


@pytest.fixture
async def people(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, User]:
    names = ("owner", "admin", "member", "viewer", "outsider")
    found = {name: await create_account(session_factory, f"{name}@example.org") for name in names}
    found["system"] = await create_account(session_factory, "system@example.org", system_admin=True)
    return found


@pytest.fixture
async def organization(
    session_factory: async_sessionmaker[AsyncSession], people: dict[str, User]
) -> uuid.UUID:
    async with session_factory() as session:
        service = OrganizationService(session)
        created = await service.create(people["owner"], " Harbour Watch ", " Harbour-Watch ")
        for name, role in (("admin", Role.ADMIN), ("member", Role.MEMBER), ("viewer", Role.VIEWER)):
            await service.add_member(people["owner"], created.id, people[name].id, role)
        return created.id


async def roles(
    session_factory: async_sessionmaker[AsyncSession], organization_id: uuid.UUID
) -> dict[uuid.UUID, Role]:
    async with session_factory() as session:
        rows = await session.scalars(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization_id
            )
        )
        return {row.user_id: row.role for row in rows}


async def test_creator_becomes_owner(
    session_factory: async_sessionmaker[AsyncSession], people: dict[str, User]
) -> None:
    async with session_factory() as session:
        created = await OrganizationService(session).create(people["owner"], "News", "news")

    assert (created.name, created.slug, created.created_by_user_id) == (
        "News",
        "news",
        people["owner"].id,
    )
    assert await roles(session_factory, created.id) == {people["owner"].id: Role.OWNER}


async def test_bad_input_and_duplicate_slug(
    session_factory: async_sessionmaker[AsyncSession], people: dict[str, User]
) -> None:
    async with session_factory() as session:
        service = OrganizationService(session)
        await service.create(people["owner"], "News", "news")
        with pytest.raises(ConflictError, match="slug already exists"):
            await service.create(people["admin"], "Other", "NEWS")
        with pytest.raises(InvalidInputError):
            await service.create(people["owner"], " ", "other")
        with pytest.raises(InvalidInputError):
            await service.create(people["owner"], "Other", "bad slug")
        assert len(list(await session.scalars(select(Organization)))) == 1


async def test_list_get_and_members(
    session_factory: async_sessionmaker[AsyncSession],
    people: dict[str, User],
    organization: uuid.UUID,
) -> None:
    async with session_factory() as session:
        service = OrganizationService(session)
        mine = await service.list_for_user(people["viewer"])
        members = await service.list_members(people["viewer"], organization)
        with pytest.raises(NotFoundError):
            await service.get(people["outsider"], organization)
        with pytest.raises(NotFoundError):
            await service.list_members(people["outsider"], organization)
        # A system admin can see any organization.
        assert (await service.get(people["system"], organization)).id == organization

    assert [(org.slug, role) for org, role in mine] == [("harbour-watch", Role.VIEWER)]
    assert [member.membership.role for member in members] == [
        Role.OWNER,
        Role.ADMIN,
        Role.MEMBER,
        Role.VIEWER,
    ]
    assert await service_list_is_empty(session_factory, people["outsider"])


async def service_list_is_empty(
    session_factory: async_sessionmaker[AsyncSession], user: User
) -> bool:
    async with session_factory() as session:
        return await OrganizationService(session).list_for_user(user) == []


async def test_owner_manages_everyone(
    session_factory: async_sessionmaker[AsyncSession],
    people: dict[str, User],
    organization: uuid.UUID,
) -> None:
    async with session_factory() as session:
        service = OrganizationService(session)
        await service.add_member(people["owner"], organization, people["outsider"].id, Role.OWNER)
        await service.change_member_role(
            people["owner"], organization, people["admin"].id, Role.MEMBER
        )
        await service.remove_member(people["owner"], organization, people["viewer"].id)

    found = await roles(session_factory, organization)
    assert found[people["outsider"].id] is Role.OWNER
    assert found[people["admin"].id] is Role.MEMBER
    assert people["viewer"].id not in found


async def test_admin_manages_members_and_viewers_only(
    session_factory: async_sessionmaker[AsyncSession],
    people: dict[str, User],
    organization: uuid.UUID,
) -> None:
    admin = people["admin"]
    async with session_factory() as session:
        service = OrganizationService(session)
        await service.add_member(admin, organization, people["outsider"].id, Role.VIEWER)
        await service.change_member_role(admin, organization, people["outsider"].id, Role.MEMBER)
        await service.remove_member(admin, organization, people["outsider"].id)
        denied = [
            service.add_member(admin, organization, people["outsider"].id, Role.ADMIN),
            service.change_member_role(admin, organization, people["member"].id, Role.ADMIN),
            service.change_member_role(admin, organization, people["owner"].id, Role.MEMBER),
            service.remove_member(admin, organization, people["owner"].id),
        ]
        for attempt in denied:
            with pytest.raises(ForbiddenError):
                await attempt


@pytest.mark.parametrize("who", ["member", "viewer"])
async def test_members_and_viewers_manage_nobody(
    session_factory: async_sessionmaker[AsyncSession],
    people: dict[str, User],
    organization: uuid.UUID,
    who: str,
) -> None:
    async with session_factory() as session:
        service = OrganizationService(session)
        with pytest.raises(ForbiddenError):
            await service.add_member(people[who], organization, people["outsider"].id, Role.VIEWER)
        with pytest.raises(ForbiddenError):
            await service.remove_member(people[who], organization, people["viewer"].id)


async def test_outsider_sees_not_found(
    session_factory: async_sessionmaker[AsyncSession],
    people: dict[str, User],
    organization: uuid.UUID,
) -> None:
    async with session_factory() as session:
        with pytest.raises(NotFoundError, match="Organization"):
            await OrganizationService(session).add_member(
                people["outsider"], organization, people["outsider"].id, Role.OWNER
            )


async def test_last_owner_is_kept(
    session_factory: async_sessionmaker[AsyncSession],
    people: dict[str, User],
    organization: uuid.UUID,
) -> None:
    async with session_factory() as session:
        service = OrganizationService(session)
        with pytest.raises(ConflictError, match="at least one owner"):
            await service.remove_member(people["owner"], organization, people["owner"].id)
        with pytest.raises(ConflictError, match="at least one owner"):
            await service.change_member_role(
                people["owner"], organization, people["owner"].id, Role.ADMIN
            )

    assert (await roles(session_factory, organization))[people["owner"].id] is Role.OWNER


async def test_add_rules(
    session_factory: async_sessionmaker[AsyncSession],
    people: dict[str, User],
    organization: uuid.UUID,
) -> None:
    async with session_factory() as session:
        service = OrganizationService(session)
        with pytest.raises(ConflictError, match="already a member"):
            await service.add_member(
                people["owner"], organization, people["member"].id, Role.VIEWER
            )
        with pytest.raises(NotFoundError, match="User"):
            await service.add_member(people["owner"], organization, uuid.uuid4(), Role.VIEWER)
        with pytest.raises(NotFoundError, match="Member"):
            await service.remove_member(people["owner"], organization, people["outsider"].id)


async def test_system_admin_can_recover(
    session_factory: async_sessionmaker[AsyncSession],
    people: dict[str, User],
    organization: uuid.UUID,
) -> None:
    async with session_factory() as session:
        service = OrganizationService(session)
        await service.add_member(people["system"], organization, people["outsider"].id, Role.OWNER)
        await service.remove_member(people["system"], organization, people["owner"].id)

    found = await roles(session_factory, organization)
    assert found[people["outsider"].id] is Role.OWNER
    assert people["owner"].id not in found
    assert people["system"].id not in found


async def test_two_owners_removed_at_once_keep_one(
    session_factory: async_sessionmaker[AsyncSession],
    people: dict[str, User],
    organization: uuid.UUID,
) -> None:
    async with session_factory() as session:
        await OrganizationService(session).change_member_role(
            people["owner"], organization, people["admin"].id, Role.OWNER
        )

    async def remove(owner: User) -> bool:
        async with session_factory() as session:
            try:
                await OrganizationService(session).remove_member(
                    people["system"], organization, owner.id
                )
            except ConflictError:
                return False
            return True

    results = await asyncio.gather(remove(people["owner"]), remove(people["admin"]))

    assert sorted(results) == [False, True]
    owners = [role for role in (await roles(session_factory, organization)).values()]
    assert owners.count(Role.OWNER) == 1
