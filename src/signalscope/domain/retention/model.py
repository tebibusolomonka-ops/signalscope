import uuid

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin

# At least a month, so audit history is never cut to nothing, and at most ten years.
MIN_SECURITY_AUDIT_DAYS = 30
MAX_SECURITY_AUDIT_DAYS = 3650


class OrganizationRetentionPolicy(TimestampMixin, Base):
    """How long an organization's records are kept. One row per organization.

    security_audit_days None, like having no row, means the organization's
    security audit events are kept for ever. Nothing is deleted without a
    policy, and only a system admin sets one.
    """

    __tablename__ = "organization_retention_policies"
    __table_args__ = (
        CheckConstraint(
            f"security_audit_days BETWEEN {MIN_SECURITY_AUDIT_DAYS} AND {MAX_SECURITY_AUDIT_DAYS}",
            name="security_audit_days_in_range",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    security_audit_days: Mapped[int | None]
