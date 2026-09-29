import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.core.errors import ForbiddenError, NotFoundError
from signalscope.domain.investigations.access import (
    InvestigationAccess,
    InvestigationPermission,
    visible_to,
)
from signalscope.domain.investigations.collaborator import (
    CollaboratorRole,
    InvestigationCollaborator,
)
from signalscope.domain.investigations.model import Investigation
from signalscope.domain.organizations.membership import OrganizationRole
from signalscope.domain.organizations.service import OrganizationService
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio

NAMES = ("owner", "admin", "editor", "viewer", "member", "outsider", "system")


async def setup(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[dict[str, User], dict[str, uuid.UUID]]:
    """An organization with one user per role, and three investigations."""
    users = {}
    for name in NAMES:
        email = f"{name}@example.org"
        users[name] = await create_account(session_factory, email, system_admin=name == "system")
    async with session_factory() as session:
        service = OrganizationService(session)
        organization = await service.create(users["owner"], "Harbour Watch", "harbour-watch")
        roles = {
            "admin": OrganizationRole.ADMIN,
            "editor": OrganizationRole.MEMBER,
            "viewer": OrganizationRole.VIEWER,
            "member": OrganizationRole.MEMBER,
        }
        for name, role in roles.items():
            await service.add_member(users["owner"], organization.id, users[name].id, role)
        shared = Investigation(title="Shared", organization_id=organization.id)
        private = Investigation(title="Private", organization_id=organization.id)
        legacy = Investigation(title="Legacy")
        session.add_all([shared, private, legacy])
        await session.flush()
        for name, role in (
            ("editor", CollaboratorRole.EDITOR),
            ("viewer", CollaboratorRole.VIEWER),
        ):
            session.add(
                InvestigationCollaborator(
                    investigation_id=shared.id, user_id=users[name].id, role=role
                )
            )
        await session.commit()
        ids = {"shared": shared.id, "private": private.id, "legacy": legacy.id}
    return users, ids


async def test_visible_investigations(session_factory: async_sessionmaker[AsyncSession]) -> None:
    users, _ = await setup(session_factory)

    visible = {}
    async with session_factory() as session:
        for name, user in users.items():
            titles = await session.scalars(select(Investigation.title).where(visible_to(user)))
            visible[name] = sorted(titles)

    assert visible == {
        "owner": ["Private", "Shared"],
        "admin": ["Private", "Shared"],
        "editor": ["Shared"],
        "viewer": ["Shared"],
        "member": [],
        "outsider": [],
        "system": ["Legacy", "Private", "Shared"],
    }


async def test_permissions(session_factory: async_sessionmaker[AsyncSession]) -> None:
    users, ids = await setup(session_factory)

    async with session_factory() as session:
        access = InvestigationAccess(session)
        shared = await session.get_one(Investigation, ids["shared"])
        legacy = await session.get_one(Investigation, ids["legacy"])
        found = {name: await access.permissions(user, shared) for name, user in users.items()}
        legacy_for_owner = await access.permissions(users["owner"], legacy)
        legacy_without_auth = await access.permissions(None, legacy)

    view, edit = InvestigationPermission.VIEW, InvestigationPermission.EDIT
    assert found["owner"] == found["admin"] == found["system"] == set(InvestigationPermission)
    assert found["editor"] == {view, edit}
    assert found["viewer"] == {view}
    assert found["member"] == found["outsider"] == set()
    assert legacy_for_owner == set()
    assert legacy_without_auth == set(InvestigationPermission)


async def test_require(session_factory: async_sessionmaker[AsyncSession]) -> None:
    users, ids = await setup(session_factory)

    async with session_factory() as session:
        access = InvestigationAccess(session)
        shared = await session.get_one(Investigation, ids["shared"])
        await access.require(users["viewer"], shared, InvestigationPermission.VIEW)
        with pytest.raises(ForbiddenError):
            await access.require(users["viewer"], shared, InvestigationPermission.EDIT)
        with pytest.raises(ForbiddenError):
            await access.require(users["editor"], shared, InvestigationPermission.DELETE)
        with pytest.raises(NotFoundError, match="Investigation was not found"):
            await access.require(users["member"], shared, InvestigationPermission.VIEW)
