from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.organizations.backup_policy import OrganizationBackupPolicy
from signalscope.domain.organizations.backup_service import OrganizationBackupService
from signalscope.domain.organizations.export_record import OrganizationExportStatus
from signalscope.domain.organizations.model import Organization
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.storage.blob import BlobStore


@dataclass(frozen=True, slots=True)
class BackupSchedulingResult:
    policies_considered: int
    backups_completed: int


BackupServiceFactory = Callable[[AsyncSession], OrganizationBackupService]


class OrganizationBackupScheduler:
    """Run due organization backup policies in bounded, locked transactions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        blobs: BlobStore,
        clock: Clock = utc_now,
        max_assets: int = 10_000,
        max_bytes: int = 500_000_000,
        service_factory: BackupServiceFactory | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.service_factory = service_factory or (
            lambda session: OrganizationBackupService(
                session, blobs, clock, max_assets=max_assets, max_bytes=max_bytes
            )
        )

    async def run_due(self, limit: int) -> BackupSchedulingResult:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        considered = 0
        completed = 0
        for _ in range(limit):
            result = await self._run_one(self.clock())
            if result is None:
                break
            considered += 1
            completed += int(result)
        return BackupSchedulingResult(considered, completed)

    async def _run_one(self, now: datetime) -> bool | None:
        async with self.session_factory() as session:
            policy = await session.scalar(
                select(OrganizationBackupPolicy)
                .where(
                    OrganizationBackupPolicy.enabled.is_(True),
                    or_(
                        OrganizationBackupPolicy.next_run_at.is_(None),
                        OrganizationBackupPolicy.next_run_at <= now,
                    ),
                )
                .order_by(
                    OrganizationBackupPolicy.next_run_at.asc().nulls_first(),
                    OrganizationBackupPolicy.organization_id,
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if policy is None:
                return None
            organization = await session.get(Organization, policy.organization_id)
            if organization is None:
                return None
            export = await self.service_factory(session).run(
                policy.organization_id, organization.created_by_user_id
            )
            return export.status is OrganizationExportStatus.COMPLETED
