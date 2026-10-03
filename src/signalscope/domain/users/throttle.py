from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base

THROTTLE_IDENTIFIER_LENGTH = 64


class AuthenticationThrottle(Base):
    """Database-backed failed-login state keyed by a one-way email identifier."""

    __tablename__ = "authentication_throttles"
    __table_args__ = (
        CheckConstraint("identifier ~ '^[0-9a-f]{64}$'", name="identifier_is_sha256_hex"),
        CheckConstraint("failure_count >= 0", name="failure_count_not_negative"),
    )
    __mapper_args__: dict[str, Any] = {"eager_defaults": True}

    identifier: Mapped[str] = mapped_column(String(THROTTLE_IDENTIFIER_LENGTH), primary_key=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True
    )
