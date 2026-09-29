import re
import unicodedata
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.domain.events.model import EVENT_TITLE_MAX_LENGTH, EVENT_TYPE_MAX_LENGTH

WHITESPACE = re.compile(r"\s+")


def normalize_event_title(title: str) -> str:
    """Return the form of an event title that is used to match events.

    The text is NFKC normalized, spaces are trimmed and collapsed, and case is
    folded. Numbers and punctuation stay, because "Flood 2024" and "Flood 2025"
    are different events.
    """
    return WHITESPACE.sub(" ", unicodedata.normalize("NFKC", title)).strip().casefold()


class EventCluster(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One real event, as reported by events from one or more documents.

    A cluster belongs to the organization of its events, so it never holds
    events of two organizations. Clusters of legacy events have none.
    """

    __tablename__ = "event_clusters"
    __table_args__ = (
        CheckConstraint("btrim(event_type) <> ''", name="event_type_not_blank"),
        CheckConstraint("btrim(canonical_title) <> ''", name="canonical_title_not_blank"),
        CheckConstraint("btrim(normalized_title) <> ''", name="normalized_title_not_blank"),
        # Finds the clusters an event could join.
        Index("ix_event_clusters_event_type_normalized_title", "event_type", "normalized_title"),
    )

    event_type: Mapped[str] = mapped_column(String(EVENT_TYPE_MAX_LENGTH))
    # The title shown for the cluster, taken from its first event.
    canonical_title: Mapped[str] = mapped_column(String(EVENT_TITLE_MAX_LENGTH))
    normalized_title: Mapped[str] = mapped_column(String(EVENT_TITLE_MAX_LENGTH))
    # The earliest known time of its events, when any is known.
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # None for clusters of legacy events.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )


class EventClusterMember(Base):
    """Puts one event in one cluster. An event is in at most one cluster."""

    __tablename__ = "event_cluster_members"
    __mapper_args__: dict[str, Any] = {"eager_defaults": True}

    # The primary key, so an event cannot join two clusters.
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event_clusters.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
