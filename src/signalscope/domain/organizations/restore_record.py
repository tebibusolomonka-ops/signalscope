import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.core.errors import ERROR_MESSAGE_MAX_LENGTH
from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.db.types import string_enum
from signalscope.domain.documents.chunk import EMPTY_JSON_OBJECT

SHA256_LENGTH = 64


class OrganizationRestoreStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class OrganizationRestore(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A durable record for restoring one organization archive."""

    __tablename__ = "organization_restores"
    __table_args__ = (
        CheckConstraint(
            "source_export_sha256 ~ '^[0-9a-f]{64}$'",
            name="source_export_sha256_is_hex",
        ),
        Index(
            "ix_organization_restores_target_created_at",
            "target_organization_id",
            "created_at",
        ),
        Index("ix_organization_restores_status", "status"),
    )

    target_organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    source_export_sha256: Mapped[str] = mapped_column(String(SHA256_LENGTH))
    status: Mapped[OrganizationRestoreStatus] = mapped_column(
        string_enum(OrganizationRestoreStatus, name="organization_restore_status"),
        default=OrganizationRestoreStatus.PLANNED,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=EMPTY_JSON_OBJECT
    )
    safe_error: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_MAX_LENGTH))
