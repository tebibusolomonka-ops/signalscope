import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.core.errors import ERROR_MESSAGE_MAX_LENGTH
from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.db.types import string_enum
from signalscope.domain.documents.chunk import EMPTY_JSON_OBJECT


class DisasterRecoveryDrillMode(StrEnum):
    VERIFICATION_ONLY = "verification_only"
    RESTORE_TEST = "restore_test"


class DisasterRecoveryDrillStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class OrganizationDisasterRecoveryDrill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A durable record of one deliberate backup or restore drill.

    A verification-only drill exports and verifies an organization and plans a
    restore without changing data. A restore-test drill also restores into a
    separate empty target organization. The record keeps only factual results,
    never archive contents or secrets.
    """

    __tablename__ = "organization_disaster_recovery_drills"
    __table_args__ = (
        Index(
            "ix_organization_dr_drills_org_created_at",
            "organization_id",
            "created_at",
        ),
        Index("ix_organization_dr_drills_status", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    target_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    mode: Mapped[DisasterRecoveryDrillMode] = mapped_column(
        string_enum(DisasterRecoveryDrillMode, name="disaster_recovery_drill_mode")
    )
    status: Mapped[DisasterRecoveryDrillStatus] = mapped_column(
        string_enum(DisasterRecoveryDrillStatus, name="disaster_recovery_drill_status"),
        default=DisasterRecoveryDrillStatus.PENDING,
    )
    backup_export_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organization_exports.id", ondelete="SET NULL")
    )
    restore_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organization_restores.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=EMPTY_JSON_OBJECT
    )
    safe_error: Mapped[str | None] = mapped_column(String(ERROR_MESSAGE_MAX_LENGTH))
