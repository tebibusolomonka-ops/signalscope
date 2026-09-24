import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """created_at and updated_at columns that the database fills in.

    Both are set by PostgreSQL with now(), which is stored as UTC. SQLAlchemy
    adds updated_at = now() to every UPDATE it runs.
    """

    # Read the database values back after INSERT and UPDATE. Async sessions
    # cannot load them later on attribute access.
    __mapper_args__: dict[str, Any] = {"eager_defaults": True}

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
