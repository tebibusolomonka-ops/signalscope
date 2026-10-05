import uuid
from contextlib import suppress
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, SignalScopeError, short_error_message
from signalscope.domain.organizations.backup_policy import (
    OrganizationBackupFrequency,
    OrganizationBackupPolicy,
)
from signalscope.domain.organizations.export_archive import (
    EXPORT_FORMAT_VERSION,
    OrganizationExportArchiveService,
)
from signalscope.domain.organizations.export_inventory import OrganizationExportInventoryService
from signalscope.domain.organizations.export_record import (
    OrganizationExport,
    OrganizationExportStatus,
)
from signalscope.domain.organizations.export_verification import (
    OrganizationExportVerificationService,
)
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.storage.blob import BlobStore

BACKUP_ARTIFACT_PREFIX = "organization-backups/"


class OrganizationBackupService:
    """Create verified organization exports for a backup policy."""

    def __init__(
        self,
        session: AsyncSession,
        blobs: BlobStore,
        clock: Clock = utc_now,
        max_assets: int = 10_000,
        max_bytes: int = 500_000_000,
    ) -> None:
        self.session = session
        self.blobs = blobs
        self.clock = clock
        self.archive = OrganizationExportArchiveService(
            OrganizationExportInventoryService(session),
            blobs,
            clock,
            max_assets,
            max_bytes,
        )

    async def run(
        self, organization_id: uuid.UUID, requested_by_user_id: uuid.UUID
    ) -> OrganizationExport:
        policy = await self.session.get(OrganizationBackupPolicy, organization_id)
        if policy is None:
            policy = OrganizationBackupPolicy(organization_id=organization_id)
            self.session.add(policy)
            await self.session.flush()

        now = self.clock()
        export_id = uuid.uuid4()
        artifact_key = f"{BACKUP_ARTIFACT_PREFIX}{export_id}.zip"
        export = OrganizationExport(
            id=export_id,
            organization_id=organization_id,
            requested_by_user_id=requested_by_user_id,
            status=OrganizationExportStatus.RUNNING,
            format_version=EXPORT_FORMAT_VERSION,
            started_at=now,
            artifact_key=artifact_key,
        )
        self.session.add(export)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise ConflictError("An organization export or backup is already running.") from error

        try:
            archive = await self.archive.build(
                organization_id, include_assets=policy.include_assets
            )
            verification = OrganizationExportVerificationService().verify(archive.data)
            if not verification.valid:
                raise ValueError("Backup export verification failed.")
            await self.blobs.put(artifact_key, archive.data)
            export.status = OrganizationExportStatus.COMPLETED
            export.finished_at = self.clock()
            export.size_bytes = archive.size_bytes
            export.sha256 = archive.sha256
            policy.last_run_at = export.finished_at
            policy.next_run_at = export.finished_at + _frequency_delta(policy.frequency)
            await self._apply_retention(organization_id, policy.retention_count, export)
        except Exception as error:
            await self.session.rollback()
            with suppress(SignalScopeError):
                await self.blobs.delete(artifact_key)
            stored_export = await self.session.get(OrganizationExport, export_id)
            stored_policy = await self.session.get(OrganizationBackupPolicy, organization_id)
            if stored_export is None or stored_policy is None:
                raise
            export = stored_export
            policy = stored_policy
            export.status = OrganizationExportStatus.FAILED
            export.finished_at = self.clock()
            export.safe_error = _safe_error(error)
            policy.next_run_at = export.finished_at + _frequency_delta(policy.frequency)

        await self.session.commit()
        return export

    async def _apply_retention(
        self,
        organization_id: uuid.UUID,
        retention_count: int,
        current: OrganizationExport,
    ) -> None:
        exports = list(
            await self.session.scalars(
                select(OrganizationExport)
                .where(
                    OrganizationExport.organization_id == organization_id,
                    OrganizationExport.status == OrganizationExportStatus.COMPLETED,
                    OrganizationExport.artifact_key.startswith(BACKUP_ARTIFACT_PREFIX),
                    OrganizationExport.id != current.id,
                )
                .order_by(OrganizationExport.finished_at.desc(), OrganizationExport.id.desc())
            )
        )
        for expired in exports[max(retention_count - 1, 0) :]:
            if expired.artifact_key is not None:
                await self.blobs.delete(expired.artifact_key)
            expired.status = OrganizationExportStatus.EXPIRED
            expired.artifact_key = None
            expired.size_bytes = None
            expired.sha256 = None


def _frequency_delta(frequency: OrganizationBackupFrequency) -> timedelta:
    if frequency is OrganizationBackupFrequency.DAILY:
        return timedelta(days=1)
    return timedelta(days=7)


def _safe_error(error: Exception) -> str:
    if isinstance(error, SignalScopeError):
        return short_error_message(str(error))
    if isinstance(error, ValueError):
        return short_error_message(str(error))
    return "Backup generation failed."
