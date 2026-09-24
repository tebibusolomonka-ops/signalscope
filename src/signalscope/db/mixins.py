import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

# Mixin columns would otherwise come after the model's own columns. This keeps
# id first and the timestamps last in every table.
FIRST = -100
LAST = 100


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4, sort_order=FIRST)


class TimestampMixin:
    """created_at and updated_at columns that the database fills in.

    Both are set by PostgreSQL with now(), which is stored as UTC. SQLAlchemy
    adds updated_at = now() to every UPDATE it runs.
    """

    # Read the database values back after INSERT and UPDATE. Async sessions
    # cannot load them later on attribute access.
    __mapper_args__: dict[str, Any] = {"eager_defaults": True}

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), sort_order=LAST
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), sort_order=LAST
    )
