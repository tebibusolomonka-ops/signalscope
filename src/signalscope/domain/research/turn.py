import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import UUIDPrimaryKeyMixin

EMPTY_JSON_ARRAY = text("'[]'::jsonb")


class ResearchTurn(UUIDPrimaryKeyMixin, Base):
    """One question in a research session, with what the answer was based on.

    Turns are history, so they are never changed after they are written.
    evidence_snapshot keeps the evidence as it was given to the answer model at
    that time: IDs, titles, links, excerpts and chunk metadata, but no vectors
    and nothing about how the model ran.
    """

    __tablename__ = "research_turns"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence"),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint("btrim(question) <> ''", name="question_not_blank"),
        CheckConstraint("jsonb_typeof(citation_ids) = 'array'", name="citation_ids_is_array"),
        CheckConstraint(
            "jsonb_typeof(evidence_snapshot) = 'array'", name="evidence_snapshot_is_array"
        ),
    )
    # Read created_at back after INSERT, as async sessions cannot load it later.
    __mapper_args__: dict[str, Any] = {"eager_defaults": True}

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_sessions.id", ondelete="CASCADE")
    )
    # 1 for the first question in the session, then counting up.
    sequence: Mapped[int]
    question: Mapped[str] = mapped_column(Text)
    # None when no answer model was used, or none was configured.
    answer: Mapped[str | None] = mapped_column(Text)
    # The evidence IDs the answer cites, such as ["E1", "E3"].
    citation_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=EMPTY_JSON_ARRAY
    )
    evidence_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=EMPTY_JSON_ARRAY
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
