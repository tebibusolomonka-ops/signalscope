import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from signalscope.domain.organizations.drill_record import (
    DisasterRecoveryDrillMode,
    DisasterRecoveryDrillStatus,
)


class OrganizationDrillRunRequest(BaseModel):
    mode: DisasterRecoveryDrillMode = DisasterRecoveryDrillMode.VERIFICATION_ONLY
    target_organization_id: uuid.UUID | None = None
    include_assets: bool = True
    user_mappings: dict[str, uuid.UUID] = {}


class OrganizationDrillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    target_organization_id: uuid.UUID | None
    requested_by_user_id: uuid.UUID
    mode: DisasterRecoveryDrillMode
    status: DisasterRecoveryDrillStatus
    backup_export_id: uuid.UUID | None
    restore_id: uuid.UUID | None
    started_at: datetime
    finished_at: datetime | None
    summary: dict[str, Any]
    safe_error: str | None
    created_at: datetime
