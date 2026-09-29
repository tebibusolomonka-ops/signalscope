import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, ForbiddenError, NotFoundError
from signalscope.domain.audit.service import AuditAction, SecurityAuditService
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.domain.users.authentication import MAX_LISTED_SESSIONS, AuthenticationService
from signalscope.domain.users.model import User
from signalscope.domain.users.passwords import PasswordHasher
from signalscope.domain.users.session import UserSession

USER_NOT_FOUND = "User was not found."
SYSTEM_ADMIN_REQUIRED = "Only system admins can manage users."
LAST_SYSTEM_ADMIN = "There must be at least one active system admin."


class UserAdministrationService:
    """User management for system admins.

    Every method checks that the actor is an active system admin, so the rule
    holds whoever calls it, not only the API. Results are User rows; the
    password credential and sessions are never loaded here.
    """

    def __init__(
        self,
        session: AsyncSession,
        actor: User,
        hasher: PasswordHasher | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self.session = session
        self.actor = actor
        self.hasher = hasher
        self.clock = clock

    async def list_users(
        self,
        *,
        query: str | None = None,
        is_active: bool | None = None,
        is_system_admin: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[User], int]:
        """Users in the order they were created, with the total that match.

        query matches part of the email or display name, ignoring case.
        """
        self._require_admin()
        conditions = []
        text = (query or "").strip()
        if text:
            conditions.append(
                or_(
                    User.normalized_email.contains(text.casefold(), autoescape=True),
                    User.display_name.icontains(text, autoescape=True),
                )
            )
        if is_active is not None:
            conditions.append(User.is_active.is_(is_active))
        if is_system_admin is not None:
            conditions.append(User.is_system_admin.is_(is_system_admin))
        users = await self.session.scalars(
            select(User)
            .where(*conditions)
            .order_by(User.created_at, User.id)
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(select(func.count()).select_from(User).where(*conditions))
        return list(users), total or 0

    async def get_user(self, user_id: uuid.UUID) -> User:
        self._require_admin()
        user = await self.session.get(User, user_id)
        if user is None:
            raise NotFoundError(USER_NOT_FOUND)
        return user

    async def create_user(
        self, email: str, display_name: str, password: str, *, is_system_admin: bool = False
    ) -> User:
        """Create an account through AuthenticationService, so hashing stays in one place."""
        self._require_admin()
        return await AuthenticationService(self.session, self.hasher).create_user(
            email,
            display_name,
            password,
            is_system_admin=is_system_admin,
            actor_user_id=self.actor.id,
        )

    async def deactivate_user(self, user_id: uuid.UUID) -> User:
        """Stop a user from signing in, and revoke their sessions in the same commit.

        The last active system admin cannot be deactivated, not even by
        themselves. Deactivating an inactive user changes nothing.
        """
        self._require_admin()
        found = await self.session.get(User, user_id)
        if found is None:
            raise NotFoundError(USER_NOT_FOUND)
        # Admins are locked before the target, always in the same order, so two
        # deactivations at the same time wait for each other instead of deadlocking.
        active_admins = await self._lock_active_admins() if found.is_system_admin else 0
        user = await self._locked(user_id)
        if not user.is_active:
            await self.session.commit()
            return user
        if user.is_system_admin and active_admins <= 1:
            await self.session.rollback()
            raise ConflictError(LAST_SYSTEM_ADMIN)
        user.is_active = False
        result = await self.session.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=self.clock())
            .execution_options(synchronize_session=False)
        )
        revoked = int(result.rowcount)  # type: ignore[attr-defined]
        self._record(AuditAction.USER_DEACTIVATED, user_id, {"revoked_sessions": revoked})
        await self._commit()
        return user

    async def reactivate_user(self, user_id: uuid.UUID) -> User:
        """Let a user sign in again. Their old sessions stay revoked."""
        self._require_admin()
        user = await self._locked(user_id)
        if not user.is_active:
            user.is_active = True
            self._record(AuditAction.USER_REACTIVATED, user_id)
        await self._commit()
        return user

    async def _locked(self, user_id: uuid.UUID) -> User:
        user = await self.session.get(User, user_id, with_for_update=True, populate_existing=True)
        if user is None:
            await self.session.rollback()
            raise NotFoundError(USER_NOT_FOUND)
        return user

    async def _lock_active_admins(self) -> int:
        """Lock every active system admin row and count them.

        A second deactivation waits here until the first commits, then counts
        without the admin that was just deactivated.
        """
        admins = await self.session.scalars(
            select(User.id)
            .where(User.is_system_admin.is_(True), User.is_active.is_(True))
            .order_by(User.id)
            .with_for_update()
        )
        return len(list(admins))

    async def list_user_sessions(self, user_id: uuid.UUID) -> list[UserSession]:
        """A user's sessions, newest first, including revoked and expired ones."""
        await self.get_user(user_id)
        found = await self.session.scalars(
            select(UserSession)
            .where(UserSession.user_id == user_id)
            .order_by(UserSession.created_at.desc(), UserSession.id)
            .limit(MAX_LISTED_SESSIONS)
        )
        return list(found)

    async def revoke_user_session(self, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
        """Revoke one session of the user. A session of someone else is not found."""
        await self.get_user(user_id)
        stored = await self.session.get(
            UserSession, session_id, with_for_update=True, populate_existing=True
        )
        if stored is None or stored.user_id != user_id:
            await self.session.rollback()
            raise NotFoundError("Session was not found.")
        if stored.revoked_at is None:
            stored.revoked_at = self.clock()
            SecurityAuditService(self.session).record(
                AuditAction.ADMIN_SESSION_REVOKED,
                actor_user_id=self.actor.id,
                resource_type="user_session",
                resource_id=session_id,
                details={"user_id": user_id},
            )
        await self._commit()

    async def revoke_user_sessions(self, user_id: uuid.UUID) -> int:
        """Revoke every active session of the user, and say how many."""
        await self.get_user(user_id)
        result = await self.session.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=self.clock())
            .execution_options(synchronize_session=False)
        )
        revoked = int(result.rowcount)  # type: ignore[attr-defined]
        self._record(AuditAction.ADMIN_SESSIONS_REVOKED, user_id, {"revoked_sessions": revoked})
        await self._commit()
        return revoked

    def _record(
        self, action: AuditAction, user_id: uuid.UUID, details: dict[str, int] | None = None
    ) -> None:
        SecurityAuditService(self.session).record(
            action,
            actor_user_id=self.actor.id,
            resource_type="user",
            resource_id=user_id,
            details=dict(details or {}),
        )

    async def _commit(self) -> None:
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    def _require_admin(self) -> None:
        if not (self.actor.is_system_admin and self.actor.is_active):
            raise ForbiddenError(SYSTEM_ADMIN_REQUIRED)
