from sqlalchemy import CheckConstraint, String, false, true
from sqlalchemy.orm import Mapped, mapped_column

from signalscope.db.base import Base
from signalscope.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from signalscope.domain.users.email import EMAIL_MAX_LENGTH

DISPLAY_NAME_MAX_LENGTH = 200


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person who can sign in.

    Passwords are kept apart, in UserPasswordCredential. Accounts are created
    by an administrator; there is no self registration.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("btrim(email) <> ''", name="email_not_blank"),
        CheckConstraint("btrim(display_name) <> ''", name="display_name_not_blank"),
    )

    # As the person wrote it, trimmed.
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH))
    # From normalize_email. Unique, so the same address in another case is the same account.
    normalized_email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), unique=True)
    display_name: Mapped[str] = mapped_column(String(DISPLAY_NAME_MAX_LENGTH))
    # An inactive user cannot sign in, and their sessions stop working.
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    # May manage everything, as a recovery path.
    is_system_admin: Mapped[bool] = mapped_column(default=False, server_default=false())
