import uuid
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.db.types import string_enum

INVESTIGATION_TITLE_MAX_LENGTH = 200


class InvestigationStatus(StrEnum):
    OPEN = "open"
    # Read only until it is opened again.
    CLOSED = "closed"


class Investigation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named collection of saved references, such as sources, events and claims.

    organization_id and created_by_user_id are NULL for legacy investigations,
    made before organizations existed. They are global: open to everyone when
    auth is off, and to system admins only when it is on.
    """

    __tablename__ = "investigations"
    __table_args__ = (CheckConstraint("btrim(title) <> ''", name="title_not_blank"),)

    title: Mapped[str] = mapped_column(String(INVESTIGATION_TITLE_MAX_LENGTH))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[InvestigationStatus] = mapped_column(
        string_enum(InvestigationStatus, name="investigation_status"),
        default=InvestigationStatus.OPEN,
    )
    # The organization that owns it. An organization with investigations cannot be deleted.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
