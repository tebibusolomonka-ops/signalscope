import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.core.errors import ForbiddenError, NotFoundError
from signalscope.domain.investigations.collaborator import CollaboratorRole
from signalscope.domain.investigations.members import InvestigationMemberService
from signalscope.domain.investigations.model import InvestigationStatus
from signalscope.domain.investigations.service import InvestigationService
from signalscope.domain.organizations.access_summary import (
    OrganizationAccessSummary,
    OrganizationAccessSummaryService,
)
from signalscope.domain.organizations.invitation import InvitationRole
from signalscope.domain.organizations.invitations import (
    InvitationStatus,
    OrganizationInvitationService,
)
from signalscope.domain.organizations.membership import OrganizationRole
from signalscope.domain.organizations.service import OrganizationService
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 1, tzinfo=UTC)
People = dict[str, User]


@pytest.fixture
async def people(session_factory: async_sessionmaker[AsyncSession]) -> People:
    found = {}
    for name in ("owner", "admin", "member", "viewer", "outsider", "system"):
        found[name] = await create_account(
            session_factory, f"{name}@example.org", system_admin=name == "system"
        )
    return found


async def new_organization(
    session_factory: async_sessionmaker[AsyncSession], owner: User
) -> uuid.UUID:
    async with session_factory() as session:
        return (await OrganizationService(session).create(owner, "Harbour", "harbour")).id


async def summary(
    session_factory: async_sessionmaker[AsyncSession], actor: User, organization: uuid.UUID
) -> OrganizationAccessSummary:
    async with session_factory() as session:
        return await OrganizationAccessSummaryService(session, actor, lambda: NOW).summary(
            organization
        )


async def test_new_organization(
    session_factory: async_sessionmaker[AsyncSession], people: People
) -> None:
    organization = await new_organization(session_factory, people["owner"])

    found = await summary(session_factory, people["owner"], organization)

    assert found.organization.slug == "harbour"
    assert found.total_members == 1
    assert found.members == {
        OrganizationRole.OWNER: 1,
        OrganizationRole.ADMIN: 0,
        OrganizationRole.MEMBER: 0,
        OrganizationRole.VIEWER: 0,
    }
    assert (found.active_members, found.inactive_members) == (1, 0)
    assert set(found.invitations.values()) == {0}
    assert set(found.investigations.values()) == {0}
    assert set(found.collaborators.values()) == {0}


async def test_counts(session_factory: async_sessionmaker[AsyncSession], people: People) -> None:
    owner = people["owner"]
    organization = await new_organization(session_factory, owner)
    async with session_factory() as session:
        service = OrganizationService(session)
        for name in ("admin", "member", "viewer"):
            await service.add_member(owner, organization, people[name].id, OrganizationRole(name))
    for email, days in (("a@example.org", 0), ("b@example.org", 0), ("c@example.org", -10)):
        async with session_factory() as session:
            await OrganizationInvitationService(
                session, owner, lambda days=days: NOW + timedelta(days=days)
            ).create_invitation(organization, email, InvitationRole.MEMBER)
    async with session_factory() as session:
        invitations = OrganizationInvitationService(session, owner, lambda: NOW)
        pending = await invitations.list_invitations(organization, InvitationStatus.PENDING)
        await invitations.revoke_invitation(organization, pending[0].id)
    async with session_factory() as session:
        first = await InvestigationService(session, owner).create(
            "Floods", organization_id=organization
        )
        second = await InvestigationService(session, owner).create(
            "Prices", organization_id=organization
        )
        await InvestigationService(session, owner).close(second.id)
        members = InvestigationMemberService(session, owner)
        await members.add(first.id, people["member"].id, CollaboratorRole.EDITOR)
        await members.add(second.id, people["member"].id, CollaboratorRole.VIEWER)
        await members.add(first.id, people["viewer"].id, CollaboratorRole.VIEWER)
    async with session_factory() as session:
        viewer = await session.get_one(User, people["viewer"].id)
        viewer.is_active = False
        await session.commit()

    found = await summary(session_factory, people["admin"], organization)

    assert found.total_members == 4
    assert found.members == {
        OrganizationRole.OWNER: 1,
        OrganizationRole.ADMIN: 1,
        OrganizationRole.MEMBER: 1,
        OrganizationRole.VIEWER: 1,
    }
    assert (found.active_members, found.inactive_members) == (3, 1)
    assert found.invitations == {
        InvitationStatus.PENDING: 1,
        InvitationStatus.ACCEPTED: 0,
        InvitationStatus.REVOKED: 1,
        InvitationStatus.EXPIRED: 1,
    }
    assert found.investigations == {InvestigationStatus.OPEN: 1, InvestigationStatus.CLOSED: 1}
    assert found.collaborators == {
        CollaboratorRole.OWNER: 2,
        CollaboratorRole.EDITOR: 1,
        CollaboratorRole.VIEWER: 2,
    }


async def test_access(session_factory: async_sessionmaker[AsyncSession], people: People) -> None:
    organization = await new_organization(session_factory, people["owner"])
    async with session_factory() as session:
        service = OrganizationService(session)
        for name in ("member", "viewer"):
            await service.add_member(
                people["owner"], organization, people[name].id, OrganizationRole(name)
            )

    assert (await summary(session_factory, people["system"], organization)).total_members == 3
    for name in ("member", "viewer"):
        with pytest.raises(ForbiddenError):
            await summary(session_factory, people[name], organization)
    with pytest.raises(NotFoundError):
        await summary(session_factory, people["outsider"], organization)
    with pytest.raises(NotFoundError):
        await summary(session_factory, people["system"], uuid.uuid4())
