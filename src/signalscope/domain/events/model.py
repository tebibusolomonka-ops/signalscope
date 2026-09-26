import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.domain.documents.chunk import EMPTY_JSON_OBJECT
from signalscope.domain.search.embedding_model import MODEL_MAX_LENGTH, PROVIDER_MAX_LENGTH

EVENT_TYPE_MAX_LENGTH = 50
EVENT_TITLE_MAX_LENGTH = 500


class Event(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Something that happened, as reported in documents.

    Nothing creates events yet. This table is the base for a later extraction
    step.
    """

    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("btrim(event_type) <> ''", name="event_type_not_blank"),
        CheckConstraint("btrim(title) <> ''", name="title_not_blank"),
    )

    # A short label, such as "election" or "flood". The set of types is not fixed yet.
    event_type: Mapped[str] = mapped_column(String(EVENT_TYPE_MAX_LENGTH))
    title: Mapped[str] = mapped_column(String(EVENT_TITLE_MAX_LENGTH))
    summary: Mapped[str | None] = mapped_column(Text)
    # When the event happened, when that is known.
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A chunk that reports an event, as found by one model.

    Evidence goes away with its chunk or its event. The event itself stays when
    a chunk goes, because other chunks may still report it.
    """

    __tablename__ = "event_evidence"
    __table_args__ = (
        UniqueConstraint("event_id", "chunk_id", "provider", "model"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_between_zero_and_one",
        ),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_is_object"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), index=True
    )
    # How sure the model was, from 0 to 1, when it says.
    confidence: Mapped[float | None]
    provider: Mapped[str] = mapped_column(String(PROVIDER_MAX_LENGTH))
    model: Mapped[str] = mapped_column(String(MODEL_MAX_LENGTH))
    # Anything else the model reports. "metadata" is taken on SQLAlchemy models.
    evidence_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=EMPTY_JSON_OBJECT
    )
