import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from signalscope.domain.organizations.backup_policy import (
    MAX_BACKUP_RETENTION_COUNT,
    MIN_BACKUP_RETENTION_COUNT,
    OrganizationBackupFrequency,
)


class OrganizationBackupPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: uuid.UUID
    enabled: bool
    frequency: OrganizationBackupFrequency
    retention_count: int
    include_assets: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    updated_at: datetime | None


class OrganizationBackupPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    frequency: OrganizationBackupFrequency
    retention_count: int = Field(ge=MIN_BACKUP_RETENTION_COUNT, le=MAX_BACKUP_RETENTION_COUNT)
    include_assets: bool
