import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.audit.service import AuditAction, SecurityAuditService
from signalscope.domain.organizations.export_record import (
    OrganizationExport,
    OrganizationExportStatus,
)
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.storage.blob import BlobStore


@dataclass(frozen=True, slots=True)
class OrganizationExportCleanupResult:
    eligible: int
    expired: int


class OrganizationExportCleanupService:
    """Expire old export artifacts in bounded batches."""

    def __init__(self, session: AsyncSession, blobs: BlobStore, clock: Clock = utc_now) -> None:
        self.session = session
        self.blobs = blobs
        self.clock = clock

    async def preview(self, retention_days: int, limit: int) -> OrganizationExportCleanupResult:
        exports = await self._eligible(retention_days, limit, lock=False)
        return OrganizationExportCleanupResult(eligible=len(exports), expired=0)

    async def run(self, retention_days: int, limit: int) -> OrganizationExportCleanupResult:
        exports = await self._eligible(retention_days, limit, lock=True)
        expired_by_organization: Counter[uuid.UUID] = Counter()
        for export in exports:
            if export.artifact_key is not None:
                await self.blobs.delete(export.artifact_key)
            export.status = OrganizationExportStatus.EXPIRED
            export.artifact_key = None
            export.size_bytes = None
            export.sha256 = None
            expired_by_organization[export.organization_id] += 1
        for organization_id, expired in expired_by_organization.items():
            SecurityAuditService(self.session).record(
                AuditAction.ORGANIZATION_EXPORT_CLEANUP,
                actor_user_id=None,
                organization_id=organization_id,
                resource_type="organization_exports",
                resource_id=organization_id,
                details={"deleted_count": expired},
            )
        await self.session.commit()
        return OrganizationExportCleanupResult(eligible=len(exports), expired=len(exports))

    async def _eligible(
        self, retention_days: int, limit: int, *, lock: bool
    ) -> list[OrganizationExport]:
        now = self.clock()
        cutoff = now - timedelta(days=retention_days)
        statement = (
            select(OrganizationExport)
            .where(
                OrganizationExport.status.in_(
                    [OrganizationExportStatus.COMPLETED, OrganizationExportStatus.FAILED]
                ),
                or_(
                    OrganizationExport.expires_at <= now,
                    func.coalesce(OrganizationExport.finished_at, OrganizationExport.created_at)
                    <= cutoff,
                ),
            )
            .order_by(
                OrganizationExport.expires_at.asc().nulls_last(),
                OrganizationExport.finished_at,
                OrganizationExport.id,
            )
            .limit(limit)
        )
        if lock:
            statement = statement.with_for_update(skip_locked=True)
        return list(await self.session.scalars(statement))
