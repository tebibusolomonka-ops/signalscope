import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin
from signalscope.db.types import string_enum

MIN_BACKUP_RETENTION_COUNT = 1
MAX_BACKUP_RETENTION_COUNT = 100


class OrganizationBackupFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


class OrganizationBackupPolicy(TimestampMixin, Base):
    """Scheduled portable backups for one organization."""

    __tablename__ = "organization_backup_policies"
    __table_args__ = (
        CheckConstraint(
            f"retention_count BETWEEN {MIN_BACKUP_RETENTION_COUNT} "
            f"AND {MAX_BACKUP_RETENTION_COUNT}",
            name="retention_count_in_range",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    frequency: Mapped[OrganizationBackupFrequency] = mapped_column(
        string_enum(OrganizationBackupFrequency, name="organization_backup_frequency"),
        default=OrganizationBackupFrequency.DAILY,
        server_default=OrganizationBackupFrequency.DAILY.value,
    )
    retention_count: Mapped[int] = mapped_column(Integer, default=7, server_default="7")
    include_assets: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
