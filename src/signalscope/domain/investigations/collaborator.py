import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin
from signalscope.db.types import string_enum


class CollaboratorRole(StrEnum):
    # Reads, edits, deletes and manages collaborators.
    OWNER = "owner"
    # Reads and edits, including items and saved research sessions.
    EDITOR = "editor"
    # Reads only.
    VIEWER = "viewer"


class InvestigationCollaborator(TimestampMixin, Base):
    """A user's role on one investigation.

    Deleting the investigation deletes its collaborators. A user who
    collaborates on an investigation cannot be deleted, like organization
    members, so no investigation loses its last owner that way.
    """

    __tablename__ = "investigation_collaborators"

    investigation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    role: Mapped[CollaboratorRole] = mapped_column(
        string_enum(CollaboratorRole, name="collaborator_role")
    )
