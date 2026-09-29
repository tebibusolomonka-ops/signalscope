import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_helpers import create_account
from signalscope.core.errors import ConflictError, ForbiddenError, NotFoundError
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.organizations.invitation import InvitationRole, OrganizationInvitation
from signalscope.domain.organizations.invitations import (
    InvitationStatus,
    NewInvitation,
    OrganizationInvitationService,
)
from signalscope.domain.organizations.membership import OrganizationRole
from signalscope.domain.organizations.service import OrganizationService
from signalscope.domain.users.authentication import hash_token
from signalscope.domain.users.model import User

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
People = dict[str, User]


@pytest.fixture
async def people(session_factory: async_sessionmaker[AsyncSession]) -> People:
    found = {}
    for name in ("owner", "admin", "member", "viewer", "outsider", "system"):
        found[name] = await create_account(
            session_factory, f"{name}@example.org", system_admin=name == "system"
        )
    return found


@pytest.fixture
async def organization(
    session_factory: async_sessionmaker[AsyncSession], people: People
) -> uuid.UUID:
    async with session_factory() as session:
        service = OrganizationService(session)
        created = await service.create(people["owner"], "Harbour", "harbour")
        for name in ("admin", "member", "viewer"):
            await service.add_member(
                people["owner"], created.id, people[name].id, OrganizationRole(name)
            )
    return created.id


async def invite(
    session_factory: async_sessionmaker[AsyncSession],
    actor: User,
    organization: uuid.UUID,
    email: str = "new@example.org",
    role: InvitationRole = InvitationRole.MEMBER,
    now: datetime = NOW,
) -> NewInvitation:
    async with session_factory() as session:
        return await OrganizationInvitationService(session, actor, lambda: now).create_invitation(
            organization, email, role
        )


async def test_owner_admin_and_system_admin_invite(
    session_factory: async_sessionmaker[AsyncSession], people: People, organization: uuid.UUID
) -> None:
    by_owner = await invite(
        session_factory, people["owner"], organization, "a@example.org", InvitationRole.ADMIN
    )
    by_admin = await invite(session_factory, people["admin"], organization, "B@Example.org")
    by_system = await invite(
        session_factory, people["system"], organization, "c@example.org", InvitationRole.ADMIN
    )

    invitation = by_admin.invitation
    assert invitation.normalized_email == "b@example.org"
    assert invitation.expires_at == NOW + timedelta(days=7)
    assert invitation.invited_by_user_id == people["admin"].id
    assert by_owner.invitation.role is InvitationRole.ADMIN
    assert by_system.invitation.invited_by_user_id == people["system"].id
    assert len(by_admin.token) >= 40
    assert invitation.token_hash == hash_token(by_admin.token) != by_admin.token
    async with session_factory() as session:
        rows = await session.execute(text("SELECT * FROM organization_invitations"))
        stored = str(rows.all())
        event = await session.scalar(
            select(SecurityAuditEvent).where(SecurityAuditEvent.resource_id == invitation.id)
        )
    for token in (by_owner.token, by_admin.token, by_system.token):
        assert token not in stored
    assert event is not None
    assert (event.action, event.details) == ("organization.invitation_created", {"role": "member"})
    assert by_admin.token not in str(event.details)


async def test_permissions(
    session_factory: async_sessionmaker[AsyncSession], people: People, organization: uuid.UUID
) -> None:
    with pytest.raises(ForbiddenError):
        await invite(session_factory, people["admin"], organization, role=InvitationRole.ADMIN)
    for name in ("member", "viewer"):
        with pytest.raises(ForbiddenError):
            await invite(session_factory, people[name], organization)
    with pytest.raises(NotFoundError, match="Organization was not found"):
        await invite(session_factory, people["outsider"], organization)
    with pytest.raises(NotFoundError):
        await invite(session_factory, people["owner"], uuid.uuid4())
    async with session_factory() as session:
        with pytest.raises(ForbiddenError):
            await OrganizationInvitationService(session, people["member"]).list_invitations(
                organization
            )


async def test_conflicts(
    session_factory: async_sessionmaker[AsyncSession], people: People, organization: uuid.UUID
) -> None:
    await invite(session_factory, people["owner"], organization)

    with pytest.raises(ConflictError, match="already pending"):
        await invite(session_factory, people["owner"], organization, "NEW@example.org")
    with pytest.raises(ConflictError, match="already a member"):
        await invite(session_factory, people["owner"], organization, "Member@example.org")
    # Once the first one expires, the address can be invited again.
    later = NOW + timedelta(days=8)
    again = await invite(session_factory, people["owner"], organization, now=later)
    assert again.invitation.expires_at == later + timedelta(days=7)


async def test_list_revoke_and_resolve(
    session_factory: async_sessionmaker[AsyncSession], people: People, organization: uuid.UUID
) -> None:
    kept = await invite(session_factory, people["owner"], organization, "kept@example.org")
    dropped = await invite(session_factory, people["owner"], organization, "dropped@example.org")
    old = await invite(
        session_factory,
        people["owner"],
        organization,
        "old@example.org",
        now=NOW - timedelta(days=30),
    )
    async with session_factory() as session:
        service = OrganizationInvitationService(session, people["admin"], lambda: NOW)
        revoked = await service.revoke_invitation(organization, dropped.invitation.id)
        again = await service.revoke_invitation(organization, dropped.invitation.id)
    assert revoked.revoked_at == NOW and again.revoked_at == NOW

    async with session_factory() as session:
        service = OrganizationInvitationService(session, people["admin"], lambda: NOW)
        listed = {
            status: [
                item.normalized_email
                for item in await service.list_invitations(organization, status)
            ]
            for status in InvitationStatus
        }
        everything = [
            item.normalized_email for item in await service.list_invitations(organization)
        ]
        resolved_id = (await service.resolve_token(kept.token)).id
        for token in (dropped.token, old.token, "unknown token"):
            with pytest.raises(NotFoundError, match="can no longer be used"):
                await service.resolve_token(token)
        with pytest.raises(ConflictError, match="expired"):
            await service.revoke_invitation(organization, old.invitation.id)
        with pytest.raises(NotFoundError):
            await service.revoke_invitation(organization, uuid.uuid4())

    assert listed == {
        InvitationStatus.PENDING: ["kept@example.org"],
        InvitationStatus.ACCEPTED: [],
        InvitationStatus.REVOKED: ["dropped@example.org"],
        InvitationStatus.EXPIRED: ["old@example.org"],
    }
    # Newest first, by when the rows were written.
    assert everything == ["old@example.org", "dropped@example.org", "kept@example.org"]
    assert resolved_id == kept.invitation.id
    async with session_factory() as session:
        revoked_id = await session.scalar(
            select(OrganizationInvitation.id).where(OrganizationInvitation.revoked_at.is_not(None))
        )
    assert revoked_id == dropped.invitation.id
