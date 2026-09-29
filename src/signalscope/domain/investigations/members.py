import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.db.errors import is_unique_violation
from signalscope.domain.audit.service import AuditAction, DetailValue, SecurityAuditService
from signalscope.domain.investigations.access import (
    NOT_FOUND,
    InvestigationAccess,
    InvestigationPermission,
)
from signalscope.domain.investigations.collaborator import (
    CollaboratorRole,
    InvestigationCollaborator,
)
from signalscope.domain.investigations.model import Investigation
from signalscope.domain.organizations.membership import OrganizationMembership
from signalscope.domain.users.model import User

LAST_OWNER_ERROR = "An investigation must keep at least one owner."
NOT_AN_ORGANIZATION_MEMBER = "User was not found in the investigation's organization."


@dataclass(frozen=True, slots=True)
class CollaboratorWithUser:
    collaborator: InvestigationCollaborator
    user: User


class InvestigationMemberService:
    """Who works on an investigation, and with which role.

    Anyone who may view the investigation may list its collaborators. Adding,
    changing and removing them needs the manage_members permission: an
    investigation owner, an organization owner or admin, or a system admin.

    Collaborators can be managed while the investigation is closed, so a
    closed investigation can still be handed over or shared for reading.

    Writes commit before they return.
    """

    def __init__(self, session: AsyncSession, actor: User) -> None:
        self.session = session
        self.actor = actor
        self.access = InvestigationAccess(session)

    async def list_collaborators(self, investigation_id: uuid.UUID) -> list[CollaboratorWithUser]:
        """Collaborators with their users, owners first."""
        investigation = await self.session.get(Investigation, investigation_id)
        if investigation is None:
            raise NotFoundError(NOT_FOUND)
        await self.access.require(self.actor, investigation, InvestigationPermission.VIEW)
        rows = await self.session.execute(
            select(InvestigationCollaborator, User)
            .join(User, User.id == InvestigationCollaborator.user_id)
            .where(InvestigationCollaborator.investigation_id == investigation_id)
            .order_by(InvestigationCollaborator.created_at, User.id)
        )
        found = [CollaboratorWithUser(collaborator, user) for collaborator, user in rows.tuples()]
        order = list(CollaboratorRole)
        return sorted(found, key=lambda item: order.index(item.collaborator.role))

    async def add(
        self, investigation_id: uuid.UUID, user_id: uuid.UUID, role: CollaboratorRole
    ) -> CollaboratorWithUser:
        """Add an active member of the investigation's organization."""
        investigation = await self._lock(investigation_id)
        user = await self.session.get(User, user_id)
        membership = (
            None
            if investigation.organization_id is None
            else await self.session.get(
                OrganizationMembership, (investigation.organization_id, user_id)
            )
        )
        if user is None or not user.is_active or membership is None:
            await self.session.rollback()
            raise NotFoundError(NOT_AN_ORGANIZATION_MEMBER)
        collaborator = InvestigationCollaborator(
            investigation_id=investigation_id, user_id=user_id, role=role
        )
        self.session.add(collaborator)
        self._record(
            AuditAction.COLLABORATOR_ADDED, investigation, {"user_id": user_id, "role": role}
        )
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            if is_unique_violation(error):
                raise ConflictError("The user is already a collaborator.") from error
            raise
        except Exception:
            await self.session.rollback()
            raise
        return CollaboratorWithUser(collaborator, user)

    async def change_role(
        self, investigation_id: uuid.UUID, user_id: uuid.UUID, role: CollaboratorRole
    ) -> CollaboratorWithUser:
        investigation = await self._lock(investigation_id)
        collaborator = await self._collaborator(investigation_id, user_id)
        if collaborator.role is CollaboratorRole.OWNER and role is not CollaboratorRole.OWNER:
            await self._keep_an_owner(investigation_id)
        self._record(
            AuditAction.COLLABORATOR_ROLE_CHANGED,
            investigation,
            {"user_id": user_id, "old_role": collaborator.role, "new_role": role},
        )
        collaborator.role = role
        await self._commit()
        user = await self.session.get_one(User, user_id)
        return CollaboratorWithUser(collaborator, user)

    async def remove(self, investigation_id: uuid.UUID, user_id: uuid.UUID) -> None:
        investigation = await self._lock(investigation_id)
        collaborator = await self._collaborator(investigation_id, user_id)
        if collaborator.role is CollaboratorRole.OWNER:
            await self._keep_an_owner(investigation_id)
        self._record(
            AuditAction.COLLABORATOR_REMOVED,
            investigation,
            {"user_id": user_id, "role": collaborator.role},
        )
        await self.session.delete(collaborator)
        await self._commit()

    def _record(
        self,
        action: AuditAction,
        investigation: Investigation,
        details: dict[str, DetailValue],
    ) -> None:
        SecurityAuditService(self.session).record(
            action,
            actor_user_id=self.actor.id,
            resource_type="investigation",
            resource_id=investigation.id,
            organization_id=investigation.organization_id,
            details=details,
        )

    async def _lock(self, investigation_id: uuid.UUID) -> Investigation:
        """Lock the investigation row, so owner checks cannot race, and check the actor."""
        investigation = await self.session.get(
            Investigation, investigation_id, with_for_update=True, populate_existing=True
        )
        if investigation is None:
            await self.session.rollback()
            raise NotFoundError(NOT_FOUND)
        try:
            await self.access.require(
                self.actor, investigation, InvestigationPermission.MANAGE_MEMBERS
            )
        except Exception:
            await self.session.rollback()
            raise
        return investigation

    async def _collaborator(
        self, investigation_id: uuid.UUID, user_id: uuid.UUID
    ) -> InvestigationCollaborator:
        collaborator = await self.session.get(
            InvestigationCollaborator, (investigation_id, user_id), populate_existing=True
        )
        if collaborator is None:
            await self.session.rollback()
            raise NotFoundError("Collaborator was not found.")
        return collaborator

    async def _keep_an_owner(self, investigation_id: uuid.UUID) -> None:
        owners = await self.session.scalar(
            select(func.count())
            .select_from(InvestigationCollaborator)
            .where(
                InvestigationCollaborator.investigation_id == investigation_id,
                InvestigationCollaborator.role == CollaboratorRole.OWNER,
            )
        )
        if (owners or 0) <= 1:
            await self.session.rollback()
            raise ConflictError(LAST_OWNER_ERROR)

    async def _commit(self) -> None:
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
