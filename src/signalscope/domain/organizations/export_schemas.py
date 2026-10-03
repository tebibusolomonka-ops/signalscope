import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from signalscope.domain.organizations.export_record import OrganizationExportStatus
from signalscope.domain.organizations.export_verification import OrganizationExportVerification


class OrganizationExportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    requested_by_user_id: uuid.UUID
    status: OrganizationExportStatus
    format_version: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    expires_at: datetime | None
    size_bytes: int | None
    sha256: str | None
    safe_error: str | None


class OrganizationExportVerificationRead(BaseModel):
    valid: bool
    format_version: str | None
    checked_files: int
    checked_records: int
    problems: tuple[str, ...]

    @classmethod
    def build(
        cls, verification: OrganizationExportVerification
    ) -> "OrganizationExportVerificationRead":
        return cls(
            valid=verification.valid,
            format_version=verification.format_version,
            checked_files=verification.checked_files,
            checked_records=verification.checked_records,
            problems=verification.problems,
        )
