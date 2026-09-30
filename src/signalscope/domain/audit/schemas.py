import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from signalscope.domain.audit.query import AuditEventWithActor
from signalscope.domain.audit.retention import MAX_SECURITY_AUDIT_DAYS, MIN_SECURITY_AUDIT_DAYS


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


class RetentionPolicyRead(BaseModel):
    """One organization's audit retention. Null days keeps events for ever."""

    model_config = ConfigDict(from_attributes=True)

    organization_id: uuid.UUID
    security_audit_days: int | None


class RetentionPolicyWrite(BaseModel):
    """How long to keep security audit events. Null keeps them for ever."""

    security_audit_days: int | None = Field(
        default=None, ge=MIN_SECURITY_AUDIT_DAYS, le=MAX_SECURITY_AUDIT_DAYS
    )


class RetentionPreviewRead(BaseModel):
    """What a cleanup would remove now. cutoff is null when kept for ever."""

    model_config = ConfigDict(from_attributes=True)

    organization_id: uuid.UUID
    security_audit_days: int | None
    cutoff: datetime | None
    deletable_count: int
    total_count: int


class RetentionCleanupRequest(BaseModel):
    """How many oldest events past the policy to delete in one bounded run."""

    limit: int = Field(default=1000, ge=1, le=10000)


class RetentionCleanupResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: uuid.UUID
    deleted: int
