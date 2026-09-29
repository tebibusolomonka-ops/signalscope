import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, ForbiddenError, NotFoundError
from signalscope.domain.audit.service import AuditAction, SecurityAuditService
from signalscope.domain.organizations.invitation import InvitationRole, OrganizationInvitation
from signalscope.domain.organizations.membership import OrganizationMembership, OrganizationRole
from signalscope.domain.organizations.model import Organization
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.domain.users.authentication import hash_token
from signalscope.domain.users.email import normalize_email
from signalscope.domain.users.model import User

DEFAULT_INVITATION_DAYS = 7
TOKEN_BYTES = 32
# Admins invite members and viewers; owners and system admins also invite admins.
ADMIN_INVITABLE_ROLES = frozenset({InvitationRole.MEMBER, InvitationRole.VIEWER})
INVALID_INVITATION = "Invitation was not found or can no longer be used."
NOT_ALLOWED = "You do not have permission to manage these invitations."


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"


def invitation_status(invitation: OrganizationInvitation, now: datetime) -> InvitationStatus:
    """The status, computed from the times. It is not stored."""
    if invitation.accepted_at is not None:
        return InvitationStatus.ACCEPTED
    if invitation.revoked_at is not None:
        return InvitationStatus.REVOKED
    if invitation.expires_at <= now:
        return InvitationStatus.EXPIRED
    return InvitationStatus.PENDING


def status_condition(status: InvitationStatus, now: datetime) -> ColumnElement[bool]:
    """The same rules as invitation_status, as SQL."""
    accepted = OrganizationInvitation.accepted_at.is_not(None)
    revoked = OrganizationInvitation.revoked_at.is_not(None)
    open_ = and_(
        OrganizationInvitation.accepted_at.is_(None), OrganizationInvitation.revoked_at.is_(None)
    )
    if status is InvitationStatus.ACCEPTED:
        return accepted
    if status is InvitationStatus.REVOKED:
        return revoked
    if status is InvitationStatus.EXPIRED:
        return and_(open_, OrganizationInvitation.expires_at <= now)
    return and_(open_, OrganizationInvitation.expires_at > now)


@dataclass(frozen=True, slots=True)
class NewInvitation:
    invitation: OrganizationInvitation
    # The raw token. It is only ever here, never stored or logged.
    token: str


class OrganizationInvitationService:
    """Invitations to join an organization, shared by hand until email exists.

    Organization owners and admins manage invitations (admins only for members
    and viewers), and system admins may manage any. Only the SHA-256 of a
    token is stored; the raw token is returned once, by create_invitation.
    Writes commit before they return.
    """

    def __init__(
        self,
        session: AsyncSession,
        actor: User,
        clock: Clock = utc_now,
        invitation_days: int = DEFAULT_INVITATION_DAYS,
    ) -> None:
        self.session = session
        self.actor = actor
        self.clock = clock
        self.invitation_days = invitation_days

    async def create_invitation(
        self, organization_id: uuid.UUID, email: str, role: InvitationRole
    ) -> NewInvitation:
        normalized = normalize_email(email)
        # The organization row lock makes a second invitation for the same
        # address wait, and then see the first one.
        await self._lock_organization(organization_id)
        await self._check_manager(organization_id, role)
        member = await self.session.scalar(
            select(OrganizationMembership.user_id)
            .join(User, User.id == OrganizationMembership.user_id)
            .where(
                OrganizationMembership.organization_id == organization_id,
                User.normalized_email == normalized,
            )
        )
        if member is not None:
            await self.session.rollback()
            raise ConflictError("The user is already a member.")
        now = self.clock()
        pending = await self.session.scalar(
            select(OrganizationInvitation.id).where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.normalized_email == normalized,
                status_condition(InvitationStatus.PENDING, now),
            )
        )
        if pending is not None:
            await self.session.rollback()
            raise ConflictError("An invitation for this email is already pending.")
        token = secrets.token_urlsafe(TOKEN_BYTES)
        invitation = OrganizationInvitation(
            organization_id=organization_id,
            normalized_email=normalized,
            role=role,
            token_hash=hash_token(token),
            expires_at=now + timedelta(days=self.invitation_days),
            invited_by_user_id=self.actor.id,
        )
        self.session.add(invitation)
        try:
            await self.session.flush()
            self._record(AuditAction.INVITATION_CREATED, invitation)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return NewInvitation(invitation=invitation, token=token)

    async def list_invitations(
        self, organization_id: uuid.UUID, status: InvitationStatus | None = None
    ) -> list[OrganizationInvitation]:
        """Invitations of the organization, newest first."""
        await self._check_organization(organization_id)
        await self._check_manager(organization_id)
        conditions = [OrganizationInvitation.organization_id == organization_id]
        if status is not None:
            conditions.append(status_condition(status, self.clock()))
        found = await self.session.scalars(
            select(OrganizationInvitation)
            .where(*conditions)
            .order_by(OrganizationInvitation.created_at.desc(), OrganizationInvitation.id)
        )
        return list(found)

    async def revoke_invitation(
        self, organization_id: uuid.UUID, invitation_id: uuid.UUID
    ) -> OrganizationInvitation:
        """Revoke a pending invitation. Revoking it again changes nothing."""
        await self._lock_organization(organization_id)
        invitation = await self.session.get(
            OrganizationInvitation, invitation_id, with_for_update=True, populate_existing=True
        )
        if invitation is None or invitation.organization_id != organization_id:
            await self.session.rollback()
            raise NotFoundError("Invitation was not found.")
        await self._check_manager(organization_id, invitation.role)
        status = invitation_status(invitation, self.clock())
        if status is InvitationStatus.PENDING:
            invitation.revoked_at = self.clock()
            self._record(AuditAction.INVITATION_REVOKED, invitation)
        elif status is not InvitationStatus.REVOKED:
            await self.session.rollback()
            raise ConflictError(f"The invitation is {status.value} and cannot be revoked.")
        await self._commit()
        return invitation

    async def resolve_token(self, token: str, *, lock: bool = False) -> OrganizationInvitation:
        """The pending invitation for a raw token.

        Unknown, expired, accepted and revoked invitations all give the same
        error. With lock, the row stays locked until the caller commits.
        """
        query = select(OrganizationInvitation).where(
            OrganizationInvitation.token_hash == hash_token(token)
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        found = await self.session.scalar(query)
        if found is None or invitation_status(found, self.clock()) is not InvitationStatus.PENDING:
            raise NotFoundError(INVALID_INVITATION)
        return found

    async def _check_organization(self, organization_id: uuid.UUID) -> None:
        """Say the organization was not found to anyone outside it."""
        organization = await self.session.get(Organization, organization_id)
        if organization is None or (
            not self.actor.is_system_admin and await self._role(organization_id) is None
        ):
            raise NotFoundError("Organization was not found.")

    async def _lock_organization(self, organization_id: uuid.UUID) -> None:
        organization = await self.session.get(
            Organization, organization_id, with_for_update=True, populate_existing=True
        )
        if organization is None or (
            not self.actor.is_system_admin and await self._role(organization_id) is None
        ):
            await self.session.rollback()
            raise NotFoundError("Organization was not found.")

    async def _check_manager(
        self, organization_id: uuid.UUID, role: InvitationRole | None = None
    ) -> None:
        if self.actor.is_system_admin:
            return
        actor_role = await self._role(organization_id)
        if actor_role is OrganizationRole.OWNER:
            return
        if actor_role is OrganizationRole.ADMIN and (role is None or role in ADMIN_INVITABLE_ROLES):
            return
        await self.session.rollback()
        raise ForbiddenError(NOT_ALLOWED)

    async def _role(self, organization_id: uuid.UUID) -> OrganizationRole | None:
        membership = await self.session.get(
            OrganizationMembership, (organization_id, self.actor.id)
        )
        return None if membership is None else membership.role

    def _record(self, action: AuditAction, invitation: OrganizationInvitation) -> None:
        SecurityAuditService(self.session).record(
            action,
            actor_user_id=self.actor.id,
            resource_type="organization_invitation",
            resource_id=invitation.id,
            organization_id=invitation.organization_id,
            details={"role": invitation.role},
        )

    async def _commit(self) -> None:
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
