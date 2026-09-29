import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import UUIDPrimaryKeyMixin
from signalscope.domain.documents.chunk import EMPTY_JSON_OBJECT

AUDIT_ACTION_MAX_LENGTH = 64
AUDIT_RESOURCE_TYPE_MAX_LENGTH = 64


class SecurityAuditEvent(UUIDPrimaryKeyMixin, Base):
    """A record of a security change, such as a login or a role change.

    Events are history and are never changed. Deleting the user or
    organization they mention sets the reference to NULL, so the event stays.
    Details hold small IDs and roles only, never passwords, tokens or hashes.
    """

    __tablename__ = "security_audit_events"
    __table_args__ = (
        CheckConstraint("btrim(action) <> ''", name="action_not_blank"),
        CheckConstraint("btrim(resource_type) <> ''", name="resource_type_not_blank"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_is_object"),
    )
    # Read created_at back after INSERT, as async sessions cannot load it later.
    __mapper_args__: dict[str, Any] = {"eager_defaults": True}

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    # For example "auth.login" or "organization.member_added".
    action: Mapped[str] = mapped_column(String(AUDIT_ACTION_MAX_LENGTH), index=True)
    resource_type: Mapped[str] = mapped_column(String(AUDIT_RESOURCE_TYPE_MAX_LENGTH))
    resource_id: Mapped[uuid.UUID | None]
    # The column is named metadata, which SQLAlchemy models use for themselves.
    details: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=EMPTY_JSON_OBJECT
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
