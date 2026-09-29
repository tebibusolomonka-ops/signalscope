import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin
from signalscope.db.types import string_enum


class OrganizationRole(StrEnum):
    # Manages everything in the organization, including other owners.
    OWNER = "owner"
    # Manages members and viewers, but not owners or admins.
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class OrganizationMembership(TimestampMixin, Base):
    """A user's role in an organization. One role per user and organization.

    Deleting an organization deletes its memberships. A user with memberships
    cannot be deleted, so an organization never loses its last owner that way.
    """

    __tablename__ = "organization_memberships"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    role: Mapped[OrganizationRole] = mapped_column(
        string_enum(OrganizationRole, name="organization_role")
    )
