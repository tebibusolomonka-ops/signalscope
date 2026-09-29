from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.organizations.invitation import OrganizationInvitation
from signalscope.domain.sources.scheduling import Clock, utc_now


@dataclass(frozen=True, slots=True)
class InvitationCleanupResult:
    checked: int
    deleted: int


class InvitationCleanupService:
    """Deletes invitations that were used, revoked or expired long ago.

    An invitation is deleted when it was accepted, revoked or expired more than
    the retention period ago. Pending invitations are never deleted.
    """

    def __init__(self, session: AsyncSession, clock: Clock = utc_now) -> None:
        self.session = session
        self.clock = clock

    async def run(self, retention_days: int, limit: int) -> InvitationCleanupResult:
        """Delete at most limit old invitations in one transaction, oldest expiry first."""
        cutoff = self.clock() - timedelta(days=retention_days)
        invitation = OrganizationInvitation
        found = await self.session.scalars(
            select(invitation.id)
            .where(
                or_(
                    invitation.accepted_at <= cutoff,
                    invitation.revoked_at <= cutoff,
                    and_(
                        invitation.accepted_at.is_(None),
                        invitation.revoked_at.is_(None),
                        invitation.expires_at <= cutoff,
                    ),
                )
            )
            .order_by(invitation.expires_at, invitation.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        ids = list(found)
        deleted = 0
        if ids:
            result = await self.session.execute(
                delete(invitation)
                .where(invitation.id.in_(ids))
                .execution_options(synchronize_session=False)
            )
            deleted = int(result.rowcount)  # type: ignore[attr-defined]
        await self.session.commit()
        return InvitationCleanupResult(checked=len(ids), deleted=deleted)
