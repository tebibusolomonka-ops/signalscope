import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from signalscope.domain.organizations.restore_record import OrganizationRestoreStatus


class OrganizationRestoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_organization_id: uuid.UUID
    requested_by_user_id: uuid.UUID
    status: OrganizationRestoreStatus
    source_export_sha256: str
    started_at: datetime
    finished_at: datetime | None
    summary: dict[str, Any]
    safe_error: str | None
