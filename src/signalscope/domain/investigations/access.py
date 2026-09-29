import uuid
from enum import StrEnum

from sqlalchemy import ColumnElement, and_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ForbiddenError, NotFoundError
from signalscope.domain.investigations.collaborator import (
    CollaboratorRole,
    InvestigationCollaborator,
)
from signalscope.domain.investigations.model import Investigation
from signalscope.domain.organizations.membership import OrganizationMembership, OrganizationRole
from signalscope.domain.users.model import User

NOT_FOUND = "Investigation was not found."


class InvestigationPermission(StrEnum):
    VIEW = "view"
    # Change details, add and remove items, and save research sessions.
    EDIT = "edit"
    DELETE = "delete"
    MANAGE_MEMBERS = "manage_members"


ALL_PERMISSIONS = frozenset(InvestigationPermission)
NO_PERMISSIONS: frozenset[InvestigationPermission] = frozenset()
FULL_ACCESS_ORGANIZATION_ROLES = frozenset({OrganizationRole.OWNER, OrganizationRole.ADMIN})
COLLABORATOR_PERMISSIONS = {
    CollaboratorRole.OWNER: ALL_PERMISSIONS,
    CollaboratorRole.EDITOR: frozenset(
        {InvestigationPermission.VIEW, InvestigationPermission.EDIT}
    ),
    CollaboratorRole.VIEWER: frozenset({InvestigationPermission.VIEW}),
}


def permissions_for(
    *,
    system_admin: bool,
    organization_id: uuid.UUID | None,
    organization_role: OrganizationRole | None,
    collaborator_role: CollaboratorRole | None,
) -> frozenset[InvestigationPermission]:
    """What a signed in user may do with one investigation.

    Legacy investigations have no organization and only system admins reach
    them. A collaborator role only counts while the user is still a member of
    the investigation's organization.
    """
    if system_admin:
        return ALL_PERMISSIONS
    if organization_id is None or organization_role is None:
        return NO_PERMISSIONS
    if organization_role in FULL_ACCESS_ORGANIZATION_ROLES:
        return ALL_PERMISSIONS
    if collaborator_role is None:
        return NO_PERMISSIONS
    return COLLABORATOR_PERMISSIONS[collaborator_role]


def visible_to(actor: User) -> ColumnElement[bool]:
    """A filter for the investigations the user may view."""
    if actor.is_system_admin:
        return true()
    organizations = select(OrganizationMembership.organization_id).where(
        OrganizationMembership.user_id == actor.id
    )
    full_access = organizations.where(
        OrganizationMembership.role.in_(FULL_ACCESS_ORGANIZATION_ROLES)
    )
    collaborating = select(InvestigationCollaborator.investigation_id).where(
        InvestigationCollaborator.user_id == actor.id
    )
    # IN never matches NULL, so legacy investigations stay hidden.
    return or_(
        Investigation.organization_id.in_(full_access),
        and_(
            Investigation.organization_id.in_(organizations),
            Investigation.id.in_(collaborating),
        ),
    )


class InvestigationAccess:
    """Checks what a user may do with an investigation.

    The actor is None when authentication is disabled. Then everyone may do
    everything, as before accounts existed.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def permissions(
        self, actor: User | None, investigation: Investigation
    ) -> frozenset[InvestigationPermission]:
        if actor is None:
            return ALL_PERMISSIONS
        organization_role = None
        collaborator_role = None
        if investigation.organization_id is not None and not actor.is_system_admin:
            membership = await self.session.get(
                OrganizationMembership, (investigation.organization_id, actor.id)
            )
            collaborator = await self.session.get(
                InvestigationCollaborator, (investigation.id, actor.id)
            )
            organization_role = None if membership is None else membership.role
            collaborator_role = None if collaborator is None else collaborator.role
        return permissions_for(
            system_admin=actor.is_system_admin,
            organization_id=investigation.organization_id,
            organization_role=organization_role,
            collaborator_role=collaborator_role,
        )

    async def require(
        self,
        actor: User | None,
        investigation: Investigation,
        permission: InvestigationPermission,
    ) -> None:
        """Raise NotFoundError when the user may not view it, ForbiddenError when only viewing."""
        permissions = await self.permissions(actor, investigation)
        if InvestigationPermission.VIEW not in permissions:
            raise NotFoundError(NOT_FOUND)
        if permission not in permissions:
            raise ForbiddenError()
