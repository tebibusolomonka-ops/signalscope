from enum import StrEnum

from sqlalchemy import CheckConstraint, String, Text
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

    There are no users yet, so investigations have no owner: every
    investigation is visible to everyone who can reach the API.
    """

    __tablename__ = "investigations"
    __table_args__ = (CheckConstraint("btrim(title) <> ''", name="title_not_blank"),)

    title: Mapped[str] = mapped_column(String(INVESTIGATION_TITLE_MAX_LENGTH))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[InvestigationStatus] = mapped_column(
        string_enum(InvestigationStatus, name="investigation_status"),
        default=InvestigationStatus.OPEN,
    )
