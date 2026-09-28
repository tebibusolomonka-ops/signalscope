import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.db.types import string_enum
from signalscope.research.evidence import ResearchMode

SESSION_TITLE_MAX_LENGTH = 200


class ResearchSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A line of questions that share a search mode and an optional source.

    Every turn in the session searches the same way, so follow-up answers are
    comparable. A source with sessions cannot be deleted, so a session never
    loses its scope without notice.
    """

    __tablename__ = "research_sessions"

    title: Mapped[str | None] = mapped_column(String(SESSION_TITLE_MAX_LENGTH))
    retrieval_mode: Mapped[ResearchMode] = mapped_column(
        string_enum(ResearchMode, name="research_mode"), default=ResearchMode.HYBRID
    )
    # When set, every turn only searches this source.
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
