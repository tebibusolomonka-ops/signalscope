import uuid
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.audit.model import SecurityAuditEvent

# Details may only use these keys, so a secret cannot be stored by mistake.
DETAIL_KEYS = frozenset(
    {"user_id", "role", "old_role", "new_role", "system_admin", "revoked_sessions"}
)
DetailValue = str | int | bool | uuid.UUID | None


class AuditAction(StrEnum):
    USER_CREATED = "user.created"
    USER_DEACTIVATED = "user.deactivated"
    USER_REACTIVATED = "user.reactivated"
    LOGIN = "auth.login"
    LOGOUT = "auth.logout"
    LOGOUT_ALL = "auth.logout_all"
    ORGANIZATION_CREATED = "organization.created"
    MEMBER_ADDED = "organization.member_added"
    MEMBER_ROLE_CHANGED = "organization.member_role_changed"
    MEMBER_REMOVED = "organization.member_removed"
    COLLABORATOR_ADDED = "investigation.collaborator_added"
    COLLABORATOR_ROLE_CHANGED = "investigation.collaborator_role_changed"
    COLLABORATOR_REMOVED = "investigation.collaborator_removed"


class SecurityAuditService:
    """Adds security audit events to the caller's transaction.

    It never commits. The caller commits the event together with the change it
    describes, so there is never an event without its change or the other way
    round. Failed logins are not recorded.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def record(
        self,
        action: AuditAction,
        *,
        actor_user_id: uuid.UUID | None,
        resource_type: str,
        resource_id: uuid.UUID | None = None,
        organization_id: uuid.UUID | None = None,
        details: dict[str, DetailValue] | None = None,
    ) -> SecurityAuditEvent:
        details = details or {}
        unknown = set(details) - DETAIL_KEYS
        if unknown:
            raise ValueError(f"Audit details do not allow: {', '.join(sorted(unknown))}")
        event = SecurityAuditEvent(
            actor_user_id=actor_user_id,
            organization_id=organization_id,
            action=action.value,
            resource_type=resource_type,
            resource_id=resource_id,
            details={
                key: str(value) if isinstance(value, uuid.UUID | str) else value
                for key, value in details.items()
            },
        )
        self.session.add(event)
        return event
