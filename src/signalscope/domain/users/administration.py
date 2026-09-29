import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ForbiddenError, NotFoundError
from signalscope.domain.users.authentication import AuthenticationService
from signalscope.domain.users.model import User
from signalscope.domain.users.passwords import PasswordHasher

USER_NOT_FOUND = "User was not found."
SYSTEM_ADMIN_REQUIRED = "Only system admins can manage users."


class UserAdministrationService:
    """User management for system admins.

    Every method checks that the actor is an active system admin, so the rule
    holds whoever calls it, not only the API. Results are User rows; the
    password credential and sessions are never loaded here.
    """

    def __init__(
        self, session: AsyncSession, actor: User, hasher: PasswordHasher | None = None
    ) -> None:
        self.session = session
        self.actor = actor
        self.hasher = hasher

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

    def _require_admin(self) -> None:
        if not (self.actor.is_system_admin and self.actor.is_active):
            raise ForbiddenError(SYSTEM_ADMIN_REQUIRED)
