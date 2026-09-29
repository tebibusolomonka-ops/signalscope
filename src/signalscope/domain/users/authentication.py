import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import (
    ConflictError,
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
    UnauthenticatedError,
)
from signalscope.db.errors import is_unique_violation
from signalscope.domain.audit.service import AuditAction, SecurityAuditService
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.domain.users.credential import UserPasswordCredential
from signalscope.domain.users.email import InvalidEmailError, normalize_email
from signalscope.domain.users.model import DISPLAY_NAME_MAX_LENGTH, User
from signalscope.domain.users.passwords import PasswordHasher
from signalscope.domain.users.session import UserSession

# The same answer for an unknown email, a wrong password and an inactive
# account, so a failed login never shows whether an account exists.
INVALID_CREDENTIALS = "Email or password is not correct."
WRONG_CURRENT_PASSWORD = "The current password is not correct."
SAME_PASSWORD = "The new password must be different from the current one."
DEFAULT_SESSION_DAYS = 7
# last_seen_at is only written when it is older than this, not on every request.
LAST_SEEN_INTERVAL = timedelta(minutes=15)
# 32 random bytes, as URL-safe text.
TOKEN_BYTES = 32
# Old sessions are removed by cleanup-auth-sessions, so this is only a guard.
MAX_LISTED_SESSIONS = 100


class InvalidCredentialsError(UnauthenticatedError):
    default_message = INVALID_CREDENTIALS


def hash_token(token: str) -> str:
    """SHA-256 of a bearer token, as lowercase hex. Only this is stored."""
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class NewSession:
    # Given to the client once. It is not stored anywhere.
    token: str
    session_id: uuid.UUID
    expires_at: datetime
    user: User


@dataclass(frozen=True, slots=True)
class ResolvedSession:
    session: UserSession
    user: User


class AuthenticationService:
    """Accounts, password checks and opaque login sessions.

    Sessions are rows in the database, found by the SHA-256 of a random bearer
    token. They can be revoked at any time. Writes commit before they return.
    """

    def __init__(
        self,
        session: AsyncSession,
        hasher: PasswordHasher | None = None,
        clock: Clock = utc_now,
        session_days: int = DEFAULT_SESSION_DAYS,
    ) -> None:
        self.session = session
        self.hasher = hasher or PasswordHasher()
        self.clock = clock
        self.session_days = session_days
        self.audit = SecurityAuditService(session)

    async def create_user(
        self,
        email: str,
        display_name: str,
        password: str,
        *,
        is_system_admin: bool = False,
        actor_user_id: uuid.UUID | None = None,
    ) -> User:
        """Create an account with a password, in one transaction.

        actor_user_id is the admin who made it, or None for the command line.
        """
        normalized = normalize_email(email)
        name = display_name.strip()
        if not name or len(name) > DISPLAY_NAME_MAX_LENGTH:
            raise InvalidInputError(
                f"Display name must be from 1 to {DISPLAY_NAME_MAX_LENGTH} characters."
            )
        password_hash = self.hasher.hash_password(password)
        user = User(
            email=email.strip(),
            normalized_email=normalized,
            display_name=name,
            is_system_admin=is_system_admin,
        )
        self.session.add(user)
        try:
            await self.session.flush()
            self.session.add(UserPasswordCredential(user_id=user.id, password_hash=password_hash))
            self.audit.record(
                AuditAction.USER_CREATED,
                actor_user_id=actor_user_id,
                resource_type="user",
                resource_id=user.id,
                details={"system_admin": is_system_admin},
            )
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            if is_unique_violation(error):
                raise ConflictError("An account with this email already exists.") from error
            raise
        except Exception:
            await self.session.rollback()
            raise
        return user

    async def authenticate_password(self, email: str, password: str) -> User:
        """The active user with this email and password, or InvalidCredentialsError.

        A stored hash with old settings is replaced after a correct password.
        """
        try:
            normalized = normalize_email(email)
        except InvalidEmailError:
            raise InvalidCredentialsError() from None
        row = (
            await self.session.execute(
                select(User, UserPasswordCredential)
                .join(UserPasswordCredential, UserPasswordCredential.user_id == User.id)
                .where(User.normalized_email == normalized)
            )
        ).one_or_none()
        if row is None:
            self.hasher.check_without_account(password)
            raise InvalidCredentialsError()
        user: User = row[0]
        credential: UserPasswordCredential = row[1]
        check = self.hasher.verify_password(password, credential.password_hash)
        if not check.valid or not user.is_active:
            raise InvalidCredentialsError()
        if check.new_hash is not None:
            credential.password_hash = check.new_hash
            await self.session.commit()
        return user

    async def create_session(self, user: User) -> NewSession:
        token = secrets.token_urlsafe(TOKEN_BYTES)
        now = self.clock()
        stored = UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=now + timedelta(days=self.session_days),
            last_seen_at=now,
            created_at=now,
        )
        self.session.add(stored)
        try:
            await self.session.flush()
            self.audit.record(
                AuditAction.LOGIN,
                actor_user_id=user.id,
                resource_type="user_session",
                resource_id=stored.id,
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return NewSession(
            token=token, session_id=stored.id, expires_at=stored.expires_at, user=user
        )

    async def login(self, email: str, password: str) -> NewSession:
        user = await self.authenticate_password(email, password)
        return await self.create_session(user)

    async def resolve_session(self, token: str) -> ResolvedSession:
        """The session and user for a bearer token, or UnauthenticatedError.

        Unknown, expired and revoked sessions, and sessions of inactive users,
        all give the same error.
        """
        row = (
            await self.session.execute(
                select(UserSession, User)
                .join(User, User.id == UserSession.user_id)
                .where(UserSession.token_hash == hash_token(token))
            )
        ).one_or_none()
        now = self.clock()
        if row is None:
            raise UnauthenticatedError()
        stored: UserSession = row[0]
        user: User = row[1]
        if stored.revoked_at is not None or stored.expires_at <= now or not user.is_active:
            raise UnauthenticatedError()
        if now - stored.last_seen_at >= LAST_SEEN_INTERVAL:
            stored.last_seen_at = now
            await self.session.commit()
        return ResolvedSession(session=stored, user=user)

    async def revoke_session(self, session_id: uuid.UUID) -> None:
        """Revoke a session. Revoking it again changes nothing."""
        stored = await self.session.get(UserSession, session_id)
        if stored is not None and stored.revoked_at is None:
            stored.revoked_at = self.clock()
            self.audit.record(
                AuditAction.LOGOUT,
                actor_user_id=stored.user_id,
                resource_type="user_session",
                resource_id=stored.id,
            )
            await self.session.commit()

    async def list_sessions(self, user_id: uuid.UUID) -> list[UserSession]:
        """A user's sessions, newest first, including revoked and expired ones."""
        found = await self.session.scalars(
            select(UserSession)
            .where(UserSession.user_id == user_id)
            .order_by(UserSession.created_at.desc(), UserSession.id)
            .limit(MAX_LISTED_SESSIONS)
        )
        return list(found)

    async def revoke_user_session(self, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
        """Revoke one of the user's own sessions. Another user's session is not found."""
        stored = await self.session.get(UserSession, session_id)
        if stored is None or stored.user_id != user_id:
            raise NotFoundError("Session was not found.")
        await self.revoke_session(session_id)

    async def revoke_all_sessions(self, user_id: uuid.UUID) -> int:
        """Revoke every active session of the user, and say how many."""
        result = await self.session.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=self.clock())
            .execution_options(synchronize_session=False)
        )
        revoked = int(result.rowcount)  # type: ignore[attr-defined]
        self.audit.record(
            AuditAction.LOGOUT_ALL,
            actor_user_id=user_id,
            resource_type="user",
            resource_id=user_id,
            details={"revoked_sessions": revoked},
        )
        await self.session.commit()
        return revoked

    async def change_password(
        self, current: ResolvedSession, current_password: str, new_password: str
    ) -> int:
        """Replace the user's password and revoke their other sessions, in one commit.

        The session used for the request stays signed in. A wrong current
        password gives one message that never says why. Returns how many
        other sessions were revoked.
        """
        user_id = current.user.id
        credential = await self.session.get(
            UserPasswordCredential, user_id, with_for_update=True, populate_existing=True
        )
        if (
            credential is None
            or not self.hasher.verify_password(current_password, credential.password_hash).valid
        ):
            await self.session.rollback()
            raise ForbiddenError(WRONG_CURRENT_PASSWORD)
        try:
            if self.hasher.verify_password(new_password, credential.password_hash).valid:
                raise InvalidInputError(SAME_PASSWORD)
            credential.password_hash = self.hasher.hash_password(new_password)
        except InvalidInputError:
            await self.session.rollback()
            raise
        now = self.clock()
        credential.password_changed_at = now
        result = await self.session.execute(
            update(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.id != current.session.id,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
            .execution_options(synchronize_session=False)
        )
        revoked = int(result.rowcount)  # type: ignore[attr-defined]
        self.audit.record(
            AuditAction.PASSWORD_CHANGED,
            actor_user_id=user_id,
            resource_type="user",
            resource_id=user_id,
            details={"revoked_sessions": revoked},
        )
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return revoked
