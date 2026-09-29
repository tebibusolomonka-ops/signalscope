import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import UUIDPrimaryKeyMixin

TOKEN_HASH_LENGTH = 64


class UserSession(UUIDPrimaryKeyMixin, Base):
    """A login session, found by the hash of its bearer token.

    The raw token is given to the client once and never stored. A session
    stops working when it expires or is revoked.
    """

    __tablename__ = "user_sessions"
    __table_args__ = (
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_is_sha256_hex"),
    )
    # Read the database defaults back after INSERT, as async sessions cannot load them later.
    __mapper_args__: dict[str, Any] = {"eager_defaults": True}

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # SHA-256 of the bearer token, as lowercase hex.
    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # Updated at most every few minutes, not on every request.
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
