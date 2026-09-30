import uuid

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin

# Conservative bounds, so a policy can never delete recent security history or
# grow so long that it never runs.
MIN_SECURITY_AUDIT_DAYS = 30
MAX_SECURITY_AUDIT_DAYS = 3650


class OrganizationAuditRetentionPolicy(TimestampMixin, Base):
    """How long one organization keeps its security audit events.

    There is one policy per organization, so the organization is the primary
    key. security_audit_days is NULL by default, which keeps events for ever;
    a number sets how many days an event is kept after it happened, within the
    bounds above. Deleting the organization deletes its policy.
    """

    __tablename__ = "organization_audit_retention_policies"
    __table_args__ = (
        CheckConstraint(
            "security_audit_days IS NULL OR "
            f"(security_audit_days >= {MIN_SECURITY_AUDIT_DAYS} "
            f"AND security_audit_days <= {MAX_SECURITY_AUDIT_DAYS})",
            name="security_audit_days_in_range",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    # NULL keeps security audit events for ever.
    security_audit_days: Mapped[int | None]
