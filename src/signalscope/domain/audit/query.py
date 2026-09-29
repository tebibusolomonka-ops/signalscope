import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ForbiddenError, InvalidInputError, NotFoundError
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.organizations.membership import OrganizationMembership, OrganizationRole
from signalscope.domain.organizations.model import Organization
from signalscope.domain.users.model import User

AUDIT_MANAGER_ROLES = frozenset({OrganizationRole.OWNER, OrganizationRole.ADMIN})
NO_AUDIT_ACCESS = "You do not have access to the security audit."
ORGANIZATION_REQUIRED = "organization_id is required unless you are a system admin."


@dataclass(frozen=True, slots=True)
class AuditEventWithActor:
    event: SecurityAuditEvent
    # None when the event has no actor, or the actor was deleted.
    actor: User | None


class SecurityAuditQueryService:
    """Reads security audit events, newest first.

    System admins read every event. Organization owners and admins read the
    events of one organization at a time, which they must name. Members,
    viewers and everyone else have no access.
    """

    def __init__(self, session: AsyncSession, actor: User) -> None:
        self.session = session
        self.actor = actor

    async def query(
        self,
        *,
        organization_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: uuid.UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditEventWithActor], int]:
        """Events that match every given filter, with the total that match.

        created_from is inclusive and created_to exclusive.
        """
        await self._check_access(organization_id)
        if created_from is not None and created_to is not None and created_from > created_to:
            raise InvalidInputError("created_from must not be after created_to.")
        event = SecurityAuditEvent
        filters = [
            (event.organization_id, organization_id),
            (event.actor_user_id, actor_user_id),
            (event.action, action),
            (event.resource_type, resource_type),
            (event.resource_id, resource_id),
        ]
        conditions = [column == value for column, value in filters if value is not None]
        if created_from is not None:
            conditions.append(event.created_at >= created_from)
        if created_to is not None:
            conditions.append(event.created_at < created_to)
        rows = await self.session.execute(
            select(event, User)
            .outerjoin(User, User.id == event.actor_user_id)
            .where(*conditions)
            .order_by(event.created_at.desc(), event.id.desc())
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(
            select(func.count()).select_from(event).where(*conditions)
        )
        found = [AuditEventWithActor(row, user) for row, user in rows.tuples()]
        return found, total or 0

    async def _check_access(self, organization_id: uuid.UUID | None) -> None:
        if self.actor.is_system_admin:
            return
        if organization_id is None:
            managed = await self.session.scalar(
                select(OrganizationMembership.organization_id)
                .where(
                    OrganizationMembership.user_id == self.actor.id,
                    OrganizationMembership.role.in_(AUDIT_MANAGER_ROLES),
                )
                .limit(1)
            )
            if managed is None:
                raise ForbiddenError(NO_AUDIT_ACCESS)
            raise InvalidInputError(ORGANIZATION_REQUIRED)
        organization = await self.session.get(Organization, organization_id)
        membership = await self.session.get(
            OrganizationMembership, (organization_id, self.actor.id)
        )
        if organization is None or membership is None:
            raise NotFoundError("Organization was not found.")
        if membership.role not in AUDIT_MANAGER_ROLES:
            raise ForbiddenError(NO_AUDIT_ACCESS)
