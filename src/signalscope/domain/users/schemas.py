import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from signalscope.domain.users.email import EMAIL_MAX_LENGTH
from signalscope.domain.users.model import DISPLAY_NAME_MAX_LENGTH
from signalscope.domain.users.passwords import PASSWORD_MAX_LENGTH


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, StringConstraints(min_length=1, max_length=EMAIL_MAX_LENGTH)]
    # Only length is limited here. A wrong length fails like a wrong password.
    password: Annotated[str, StringConstraints(min_length=1, max_length=PASSWORD_MAX_LENGTH)]


class UserRead(BaseModel):
    """A user as others may see them. Never with a password or hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    is_active: bool
    is_system_admin: bool


class LoginResponse(BaseModel):
    # Shown only now. Send it as "Authorization: Bearer <access_token>".
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserRead


class CurrentUserRead(BaseModel):
    user: UserRead
    session_id: uuid.UUID
    expires_at: datetime


class SessionRead(BaseModel):
    """A login session. The token and its hash are never shown."""

    session_id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    revoked: bool
    revoked_at: datetime | None
    # True for the session of the token used for this request.
    current_session: bool


class AdminUserRead(UserRead):
    """A user for system admins. Still never with a password, hash or session."""

    created_at: datetime
    updated_at: datetime


class AdminUserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, StringConstraints(min_length=1, max_length=EMAIL_MAX_LENGTH)]
    display_name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=DISPLAY_NAME_MAX_LENGTH),
    ]
    # The policy (12 to 1024 characters) is checked by the service.
    password: Annotated[str, StringConstraints(min_length=1, max_length=PASSWORD_MAX_LENGTH)]
    is_system_admin: bool = False
