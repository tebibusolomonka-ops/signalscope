from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.domain.users.session import UserSession


@dataclass(frozen=True, slots=True)
class SessionCleanupResult:
    checked: int
    deleted: int


class SessionCleanupService:
    """Deletes login sessions that ended long ago.

    A session is deleted when it expired, or was revoked, more than the
    retention period ago. Active sessions are never deleted.
    """

    def __init__(self, session: AsyncSession, clock: Clock = utc_now) -> None:
        self.session = session
        self.clock = clock

    async def run(self, retention_days: int, limit: int) -> SessionCleanupResult:
        """Delete at most limit old sessions in one transaction."""
        cutoff = self.clock() - timedelta(days=retention_days)
        found = await self.session.scalars(
            select(UserSession.id)
            .where(
                or_(
                    UserSession.expires_at <= cutoff,
                    and_(UserSession.revoked_at.is_not(None), UserSession.revoked_at <= cutoff),
                )
            )
            .order_by(UserSession.expires_at, UserSession.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        ids = list(found)
        deleted = 0
        if ids:
            result = await self.session.execute(
                delete(UserSession)
                .where(UserSession.id.in_(ids))
                .execution_options(synchronize_session=False)
            )
            deleted = int(result.rowcount)  # type: ignore[attr-defined]
        await self.session.commit()
        return SessionCleanupResult(checked=len(ids), deleted=deleted)
