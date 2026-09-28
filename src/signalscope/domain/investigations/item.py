import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import UUIDPrimaryKeyMixin
from signalscope.db.types import string_enum
from signalscope.domain.documents.chunk import EMPTY_JSON_OBJECT

ITEM_LABEL_MAX_LENGTH = 200


class InvestigationItemType(StrEnum):
    SOURCE = "source"
    DOCUMENT = "document"
    EVENT = "event"
    EVENT_CLUSTER = "event_cluster"
    ENTITY = "entity"
    CLAIM = "claim"
    RESEARCH_SESSION = "research_session"


class InvestigationItem(UUIDPrimaryKeyMixin, Base):
    """A saved reference to one record, with a small snapshot of it.

    reference_id can point at several tables, chosen by item_type, so it has no
    foreign key. The service checks that the record exists when the item is
    added. The snapshot keeps what the record looked like then, so the item
    stays useful if the record changes or is deleted. Items are history and
    are never changed after they are written.
    """

    __tablename__ = "investigation_items"
    __table_args__ = (
        UniqueConstraint("investigation_id", "item_type", "reference_id"),
        CheckConstraint("jsonb_typeof(snapshot) = 'object'", name="snapshot_is_object"),
    )
    # Read created_at back after INSERT, as async sessions cannot load it later.
    __mapper_args__: dict[str, Any] = {"eager_defaults": True}

    investigation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE")
    )
    item_type: Mapped[InvestigationItemType] = mapped_column(
        string_enum(InvestigationItemType, name="investigation_item_type")
    )
    reference_id: Mapped[uuid.UUID]
    # An optional note on why the item was saved.
    label: Mapped[str | None] = mapped_column(String(ITEM_LABEL_MAX_LENGTH))
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=EMPTY_JSON_OBJECT
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
