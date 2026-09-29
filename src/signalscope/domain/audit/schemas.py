import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from signalscope.domain.audit.query import AuditEventWithActor


class AuditActorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str


class AuditEventRead(BaseModel):
    """One security audit event. Details hold IDs, roles and counts only."""

    id: uuid.UUID
    # None when there was no actor, or the account was deleted.
    actor: AuditActorRead | None
    organization_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: uuid.UUID | None
    metadata: dict[str, Any]
    created_at: datetime

    @classmethod
    def build(cls, found: AuditEventWithActor) -> "AuditEventRead":
        event = found.event
        return cls(
            id=event.id,
            actor=None if found.actor is None else AuditActorRead.model_validate(found.actor),
            organization_id=event.organization_id,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            metadata=dict(event.details),
            created_at=event.created_at,
        )
