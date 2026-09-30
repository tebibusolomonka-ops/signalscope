import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from signalscope.domain.retention.model import MAX_SECURITY_AUDIT_DAYS, MIN_SECURITY_AUDIT_DAYS

MAX_CLEANUP_LIMIT = 10_000


class RetentionPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: uuid.UUID
    # null: security audit events are kept indefinitely.
    security_audit_days: int | None
    # null when no policy was ever set.
    updated_at: datetime | None


class RetentionPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # null keeps events indefinitely again.
    security_audit_days: int | None = Field(ge=MIN_SECURITY_AUDIT_DAYS, le=MAX_SECURITY_AUDIT_DAYS)


class AuditRetentionPreviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: uuid.UUID
    retention_days: int | None
    # Events created before this would be deleted. null without a policy.
    cutoff: datetime | None
    eligible_count: int


class AuditCleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=1000, ge=1, le=MAX_CLEANUP_LIMIT)
    # Must be true: deleted audit events cannot be brought back.
    confirm: bool = False


class AuditCleanupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: uuid.UUID
    retention_days: int
    cutoff: datetime
    deleted_count: int
