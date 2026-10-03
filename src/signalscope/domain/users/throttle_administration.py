from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ForbiddenError, NotFoundError
from signalscope.domain.audit.service import AuditAction, SecurityAuditService
from signalscope.domain.users.administration import SYSTEM_ADMIN_REQUIRED
from signalscope.domain.users.model import User
from signalscope.domain.users.throttle import THROTTLE_IDENTIFIER_LENGTH, AuthenticationThrottle

THROTTLE_NOT_FOUND = "Login throttle was not found."


def valid_throttle_identifier(value: str) -> bool:
    return len(value) == THROTTLE_IDENTIFIER_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


class LoginThrottleAdministrationService:
    """Inspect and clear login throttle state without exposing email addresses."""

    def __init__(self, session: AsyncSession, actor: User | None = None) -> None:
        self.session = session
        self.actor = actor

    async def list_throttles(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[AuthenticationThrottle], int]:
        self._require_admin()
        found = await self.session.scalars(
            select(AuthenticationThrottle)
            .order_by(AuthenticationThrottle.updated_at.desc(), AuthenticationThrottle.identifier)
            .limit(limit)
            .offset(offset)
        )
        total = await self.session.scalar(select(func.count()).select_from(AuthenticationThrottle))
        return list(found), total or 0

    async def clear(self, identifier: str) -> None:
        self._require_admin()
        if not valid_throttle_identifier(identifier):
            raise NotFoundError(THROTTLE_NOT_FOUND)
        throttle = await self.session.get(AuthenticationThrottle, identifier, with_for_update=True)
        if throttle is None:
            await self.session.rollback()
            raise NotFoundError(THROTTLE_NOT_FOUND)
        await self.session.delete(throttle)
        SecurityAuditService(self.session).record(
            AuditAction.LOGIN_THROTTLE_CLEARED,
            actor_user_id=self.actor.id if self.actor else None,
            resource_type="authentication_throttle",
        )
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    def _require_admin(self) -> None:
        if self.actor is not None and not (self.actor.is_system_admin and self.actor.is_active):
            raise ForbiddenError(SYSTEM_ADMIN_REQUIRED)
