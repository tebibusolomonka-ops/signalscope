import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.db.types import string_enum
from signalscope.domain.users.email import EMAIL_MAX_LENGTH
from signalscope.domain.users.session import TOKEN_HASH_LENGTH


class InvitationRole(StrEnum):
    """Roles an invitation may give. Owners are made by changing a member's role."""

    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class OrganizationInvitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An invitation for an email address to join an organization with a role.

    Only the SHA-256 of the invitation token is stored; the token itself is
    shown once, when the invitation is made. An invitation is pending until it
    is accepted, revoked or expires. Old rows stay as history until cleanup,
    so the same address can be invited again later.
    """

    __tablename__ = "organization_invitations"
    __table_args__ = (
        CheckConstraint("btrim(normalized_email) <> ''", name="normalized_email_not_blank"),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_is_sha256_hex"),
        CheckConstraint(
            "accepted_at IS NULL OR revoked_at IS NULL", name="not_accepted_and_revoked"
        ),
    )
    # Read the database defaults back after INSERT, as async sessions cannot load them later.
    __mapper_args__: dict[str, Any] = {"eager_defaults": True}

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    # From normalize_email, like User.normalized_email.
    normalized_email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), index=True)
    role: Mapped[InvitationRole] = mapped_column(
        string_enum(InvitationRole, name="invitation_role")
    )
    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
