import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.core.errors import ERROR_MESSAGE_MAX_LENGTH
from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.db.types import string_enum

EXPORT_FORMAT_VERSION_MAX_LENGTH = 20
EXPORT_ARTIFACT_KEY_MAX_LENGTH = 500
SHA256_LENGTH = 64


class OrganizationExportStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class OrganizationExport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A durable record for one portable organization export."""

    __tablename__ = "organization_exports"
    __table_args__ = (
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="size_bytes_not_negative"),
        CheckConstraint("sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'", name="sha256_is_hex"),
        Index("ix_organization_exports_organization_created_at", "organization_id", "created_at"),
        Index("ix_organization_exports_status_expires_at", "status", "expires_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[OrganizationExportStatus] = mapped_column(
        string_enum(OrganizationExportStatus, name="organization_export_status"),
        default=OrganizationExportStatus.PENDING,
    )
    format_version: Mapped[str] = mapped_column(String(EXPORT_FORMAT_VERSION_MAX_LENGTH))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    artifact_key: Mapped[str | None] = mapped_column(String(EXPORT_ARTIFACT_KEY_MAX_LENGTH))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(SHA256_LENGTH))
    safe_error: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_MAX_LENGTH))
