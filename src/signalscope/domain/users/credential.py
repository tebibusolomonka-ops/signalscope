import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base

PASSWORD_HASH_MAX_LENGTH = 512


class UserPasswordCredential(Base):
    """The password hash of one user. Never returned by any API."""

    __tablename__ = "user_password_credentials"
    # Read the database defaults back after INSERT, as async sessions cannot load them later.
    __mapper_args__: dict[str, Any] = {"eager_defaults": True}

    # One credential per user. It goes away with the user.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # An encoded Argon2id hash, with its salt and settings.
    password_hash: Mapped[str] = mapped_column(String(PASSWORD_HASH_MAX_LENGTH))
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
