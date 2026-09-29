import re
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.core.errors import InvalidInputError
from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin

ORGANIZATION_NAME_MAX_LENGTH = 200
SLUG_MAX_LENGTH = 63
# Lowercase letters and digits, in groups joined by single hyphens.
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class InvalidSlugError(InvalidInputError):
    default_message = (
        "Slug must be lowercase letters, digits and single hyphens, "
        f"not starting or ending with a hyphen, and at most {SLUG_MAX_LENGTH} characters."
    )


def normalize_slug(slug: str) -> str:
    """Trim and lowercase a slug, and check its form."""
    normalized = slug.strip().lower()
    if len(normalized) > SLUG_MAX_LENGTH or not SLUG_PATTERN.fullmatch(normalized):
        raise InvalidSlugError()
    return normalized


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A group of users who share investigations."""

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
    )

    name: Mapped[str] = mapped_column(String(ORGANIZATION_NAME_MAX_LENGTH))
    slug: Mapped[str] = mapped_column(String(SLUG_MAX_LENGTH), unique=True)
    # A user who created an organization cannot be deleted while it exists.
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
