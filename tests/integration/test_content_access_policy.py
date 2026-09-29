import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.core.errors import (
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
    UnauthenticatedError,
)
from signalscope.domain.documents.model import Document
from signalscope.domain.organizations.membership import OrganizationRole
from signalscope.domain.organizations.service import OrganizationService
from signalscope.domain.sources.model import Source, SourceType
from signalscope.domain.tenancy.policy import ContentAccessPolicy, ContentCapability
from signalscope.domain.tenancy.scope import ContentScope
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio

READ, CONTRIBUTE, MANAGE = (
    ContentCapability.READ,
    ContentCapability.CONTRIBUTE,
    ContentCapability.MANAGE,
)


class World:
    users: dict[str, User]
    harbour: uuid.UUID
    owned_source: uuid.UUID
    owned_document: uuid.UUID
    legacy_source: uuid.UUID
    legacy_document: uuid.UUID


@pytest.fixture
async def world(session_factory: async_sessionmaker[AsyncSession]) -> World:
    found = World()
    found.users = {}
    for name in ("owner", "admin", "member", "viewer", "outsider", "system"):
        found.users[name] = await create_account(
            session_factory, f"{name}@example.org", system_admin=name == "system"
        )
    async with session_factory() as session:
        service = OrganizationService(session)
        harbour = await service.create(found.users["owner"], "Harbour", "harbour")
        for name in ("admin", "member", "viewer"):
            await service.add_member(
                found.users["owner"], harbour.id, found.users[name].id, OrganizationRole(name)
            )
        found.harbour = harbour.id
        owned = Source(type=SourceType.RSS, name="Owned", organization_id=harbour.id)
        legacy = Source(type=SourceType.RSS, name="Legacy")
        session.add_all([owned, legacy])
        await session.flush()
        owned_document = Document(source_id=owned.id, title="Owned")
        legacy_document = Document(source_id=legacy.id, title="Legacy")
        session.add_all([owned_document, legacy_document])
        await session.commit()
        found.owned_source, found.legacy_source = owned.id, legacy.id
        found.owned_document, found.legacy_document = owned_document.id, legacy_document.id
    return found


def policy(session: AsyncSession, actor: User | None) -> ContentAccessPolicy:
    return ContentAccessPolicy(session, actor)


async def test_scope_for_each_role(
    session_factory: async_sessionmaker[AsyncSession], world: World
) -> None:
    allowed = {
        "owner": {READ, CONTRIBUTE, MANAGE},
        "admin": {READ, CONTRIBUTE, MANAGE},
        "member": {READ, CONTRIBUTE},
        "viewer": {READ},
        "system": {READ, CONTRIBUTE, MANAGE},
    }
    async with session_factory() as session:
        for name, capabilities in allowed.items():
            for capability in ContentCapability:
                call = policy(session, world.users[name]).scope(world.harbour, capability)
                if capability in capabilities:
                    assert await call == ContentScope.organization(world.harbour)
                else:
                    with pytest.raises(ForbiddenError):
                        await call


async def test_scope_errors_and_legacy(
    session_factory: async_sessionmaker[AsyncSession], world: World
) -> None:
    async with session_factory() as session:
        assert await policy(session, None).scope(None) == ContentScope.unrestricted()
        assert await policy(session, None).scope(world.harbour) == ContentScope.unrestricted()
        assert await policy(session, world.users["system"]).scope(None) == ContentScope.legacy()
        with pytest.raises(InvalidInputError):
            await policy(session, world.users["owner"]).scope(None)
        with pytest.raises(NotFoundError):
            await policy(session, world.users["outsider"]).scope(world.harbour)
        with pytest.raises(NotFoundError):
            await policy(session, world.users["system"]).scope(uuid.uuid4())
        inactive = world.users["member"]
        inactive.is_active = False
        with pytest.raises(UnauthenticatedError):
            await policy(session, inactive).scope(world.harbour)


async def test_resources(session_factory: async_sessionmaker[AsyncSession], world: World) -> None:
    async with session_factory() as session:
        viewer = policy(session, world.users["viewer"])
        assert (await viewer.authorize_source(world.owned_source)).name == "Owned"
        assert (await viewer.authorize_document(world.owned_document)).title == "Owned"
        with pytest.raises(ForbiddenError):
            await viewer.authorize_source(world.owned_source, MANAGE)
        with pytest.raises(ForbiddenError):
            await viewer.authorize_document(world.owned_document, CONTRIBUTE)
        member = policy(session, world.users["member"])
        await member.authorize_document(world.owned_document, CONTRIBUTE)
        await policy(session, world.users["admin"]).authorize_source(world.owned_source, MANAGE)

        outsider = policy(session, world.users["outsider"])
        with pytest.raises(NotFoundError, match="Source was not found"):
            await outsider.authorize_source(world.owned_source)
        with pytest.raises(NotFoundError, match="Document was not found"):
            await outsider.authorize_document(world.owned_document)
        # Legacy content is for system admins only, even for organization owners.
        with pytest.raises(NotFoundError):
            await policy(session, world.users["owner"]).authorize_source(world.legacy_source)
        with pytest.raises(NotFoundError):
            await viewer.authorize_document(world.legacy_document)
        system = policy(session, world.users["system"])
        await system.authorize_source(world.legacy_source, MANAGE)
        await system.authorize_document(world.owned_document, MANAGE)
        await policy(session, None).authorize_document(world.legacy_document, MANAGE)
        with pytest.raises(NotFoundError):
            await system.authorize_source(uuid.uuid4())
