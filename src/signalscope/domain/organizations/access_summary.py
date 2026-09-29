import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ForbiddenError, NotFoundError
from signalscope.domain.investigations.collaborator import (
    CollaboratorRole,
    InvestigationCollaborator,
)
from signalscope.domain.investigations.model import Investigation, InvestigationStatus
from signalscope.domain.organizations.invitation import OrganizationInvitation
from signalscope.domain.organizations.invitations import InvitationStatus, status_condition
from signalscope.domain.organizations.membership import OrganizationMembership, OrganizationRole
from signalscope.domain.organizations.model import Organization
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.domain.users.model import User

SUMMARY_ROLES = frozenset({OrganizationRole.OWNER, OrganizationRole.ADMIN})


@dataclass(frozen=True, slots=True)
class OrganizationAccessSummary:
    """Counts of who has access to an organization and its investigations.

    Facts only: no scores or rankings of users.
    """

    organization: Organization
    members: dict[OrganizationRole, int]
    active_members: int
    inactive_members: int
    invitations: dict[InvitationStatus, int]
    investigations: dict[InvestigationStatus, int]
    collaborators: dict[CollaboratorRole, int]

    @property
    def total_members(self) -> int:
        return sum(self.members.values())


class OrganizationAccessSummaryService:
    """Access counts for one organization, for its owners and admins and system admins."""

    def __init__(self, session: AsyncSession, actor: User, clock: Clock = utc_now) -> None:
        self.session = session
        self.actor = actor
        self.clock = clock

    async def summary(self, organization_id: uuid.UUID) -> OrganizationAccessSummary:
        organization = await self._check_access(organization_id)
        membership = OrganizationMembership
        roles = await self.session.execute(
            select(membership.role, func.count())
            .where(membership.organization_id == organization_id)
            .group_by(membership.role)
        )
        members = dict.fromkeys(OrganizationRole, 0)
        members.update({OrganizationRole(row[0]): int(row[1]) for row in roles})

        activity = await self.session.execute(
            select(User.is_active, func.count())
            .join(membership, membership.user_id == User.id)
            .where(membership.organization_id == organization_id)
            .group_by(User.is_active)
        )
        active = {bool(row[0]): int(row[1]) for row in activity}

        now = self.clock()
        invitation_counts = (
            await self.session.execute(
                select(
                    *[
                        func.count().filter(status_condition(status, now))
                        for status in InvitationStatus
                    ]
                ).where(OrganizationInvitation.organization_id == organization_id)
            )
        ).one()
        invitations = {
            status: int(count)
            for status, count in zip(InvitationStatus, invitation_counts, strict=True)
        }

        statuses = await self.session.execute(
            select(Investigation.status, func.count())
            .where(Investigation.organization_id == organization_id)
            .group_by(Investigation.status)
        )
        investigations = dict.fromkeys(InvestigationStatus, 0)
        investigations.update({InvestigationStatus(row[0]): int(row[1]) for row in statuses})

        collaborator_roles = await self.session.execute(
            select(InvestigationCollaborator.role, func.count())
            .join(Investigation, Investigation.id == InvestigationCollaborator.investigation_id)
            .where(Investigation.organization_id == organization_id)
            .group_by(InvestigationCollaborator.role)
        )
        collaborators = dict.fromkeys(CollaboratorRole, 0)
        collaborators.update({CollaboratorRole(row[0]): int(row[1]) for row in collaborator_roles})

        return OrganizationAccessSummary(
            organization=organization,
            members=members,
            active_members=active.get(True, 0),
            inactive_members=active.get(False, 0),
            invitations=invitations,
            investigations=investigations,
            collaborators=collaborators,
        )

    async def _check_access(self, organization_id: uuid.UUID) -> Organization:
        organization = await self.session.get(Organization, organization_id)
        if organization is None:
            raise NotFoundError("Organization was not found.")
        if self.actor.is_system_admin:
            return organization
        membership = await self.session.get(
            OrganizationMembership, (organization_id, self.actor.id)
        )
        if membership is None:
            raise NotFoundError("Organization was not found.")
        if membership.role not in SUMMARY_ROLES:
            raise ForbiddenError("Only organization owners and admins can see this summary.")
        return organization
