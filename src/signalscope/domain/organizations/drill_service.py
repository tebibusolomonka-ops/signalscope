import uuid
from collections.abc import Mapping

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import (
    ConflictError,
    InvalidInputError,
    ServiceUnavailableError,
    SignalScopeError,
    short_error_message,
)
from signalscope.domain.organizations.archive_reader import OrganizationArchiveReader
from signalscope.domain.organizations.drill_record import (
    DisasterRecoveryDrillMode,
    DisasterRecoveryDrillStatus,
    OrganizationDisasterRecoveryDrill,
)
from signalscope.domain.organizations.export_archive import OrganizationExportArchiveService
from signalscope.domain.organizations.export_inventory import OrganizationExportInventoryService
from signalscope.domain.organizations.export_verification import (
    OrganizationExportVerificationService,
)
from signalscope.domain.organizations.model import Organization
from signalscope.domain.organizations.restore_conflicts import OrganizationRestoreConflictService
from signalscope.domain.organizations.restore_inventory import OrganizationRestoreInventoryService
from signalscope.domain.organizations.restore_record import (
    OrganizationRestore,
    OrganizationRestoreStatus,
)
from signalscope.domain.organizations.restore_service import OrganizationRestoreService
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.storage.blob import BlobStore


class OrganizationDisasterRecoveryDrillService:
    """Exercise backup and restore readiness and record the factual result.

    A verification-only drill builds a verified archive and plans a restore
    without changing data. A restore-test drill also restores into a separate
    empty target organization using the existing constrained restore service.
    It never auto-creates or deletes organizations, never restores credentials,
    and never weakens the restore restrictions.
    """

    def __init__(
        self,
        session: AsyncSession,
        blobs: BlobStore,
        *,
        clock: Clock = utc_now,
        max_assets: int = 10_000,
        max_bytes: int = 500_000_000,
    ) -> None:
        self.session = session
        self.blobs = blobs
        self.clock = clock
        self.archive = OrganizationExportArchiveService(
            OrganizationExportInventoryService(session), blobs, clock, max_assets, max_bytes
        )

    async def run(
        self,
        organization_id: uuid.UUID,
        requested_by_user_id: uuid.UUID,
        *,
        mode: DisasterRecoveryDrillMode,
        target_organization_id: uuid.UUID | None = None,
        include_assets: bool = True,
        user_mappings: Mapping[str, uuid.UUID] | None = None,
    ) -> OrganizationDisasterRecoveryDrill:
        if mode is DisasterRecoveryDrillMode.RESTORE_TEST and target_organization_id is None:
            raise InvalidInputError("A restore-test drill needs an empty target organization.")
        if (
            mode is DisasterRecoveryDrillMode.RESTORE_TEST
            and await self.session.get(Organization, target_organization_id) is None
        ):
            raise InvalidInputError("The restore-test target organization does not exist.")

        now = self.clock()
        drill_id = uuid.uuid4()
        drill = OrganizationDisasterRecoveryDrill(
            id=drill_id,
            organization_id=organization_id,
            target_organization_id=target_organization_id,
            requested_by_user_id=requested_by_user_id,
            mode=mode,
            status=DisasterRecoveryDrillStatus.RUNNING,
            started_at=now,
        )
        self.session.add(drill)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise ConflictError(
                "A restore-test drill is already active for this target."
            ) from error

        try:
            if mode is DisasterRecoveryDrillMode.VERIFICATION_ONLY:
                summary = await self._verify(organization_id, include_assets)
            else:
                assert target_organization_id is not None
                summary, restore = await self._restore_test(
                    organization_id,
                    target_organization_id,
                    requested_by_user_id,
                    include_assets,
                    user_mappings or {},
                )
                drill.restore_id = restore.id
            drill.status = DisasterRecoveryDrillStatus.COMPLETED
            drill.summary = summary
        except SignalScopeError as error:
            drill.status = DisasterRecoveryDrillStatus.FAILED
            drill.safe_error = short_error_message(str(error))
        except Exception:
            drill.status = DisasterRecoveryDrillStatus.FAILED
            drill.safe_error = "Disaster recovery drill failed."
        drill.finished_at = self.clock()
        await self.session.commit()
        return drill

    async def _verify(self, organization_id: uuid.UUID, include_assets: bool) -> dict[str, object]:
        archive = await self.archive.build(organization_id, include_assets=include_assets)
        verification = OrganizationExportVerificationService().verify(archive.data)
        if not verification.valid:
            raise ServiceUnavailableError("The backup archive did not verify.")
        read = OrganizationArchiveReader().read(archive.data)
        inventory = OrganizationRestoreInventoryService().build(read)
        # A verification drill has no restore target, so there are no
        # target conflicts. The restore warnings are still worth recording.
        conflicts = await OrganizationRestoreConflictService(self.session).analyze(read)
        return {
            "mode": DisasterRecoveryDrillMode.VERIFICATION_ONLY.value,
            "archive_sha256": archive.sha256,
            "archive_size_bytes": archive.size_bytes,
            "counts": inventory.counts,
            "asset_count": inventory.asset_count,
            "plan_conflicts": [],
            "plan_warnings": list(conflicts.warnings),
        }

    async def _restore_test(
        self,
        organization_id: uuid.UUID,
        target_organization_id: uuid.UUID,
        requested_by_user_id: uuid.UUID,
        include_assets: bool,
        user_mappings: Mapping[str, uuid.UUID],
    ) -> tuple[dict[str, object], OrganizationRestore]:
        archive = await self.archive.build(organization_id, include_assets=include_assets)
        verification = OrganizationExportVerificationService().verify(archive.data)
        if not verification.valid:
            raise ServiceUnavailableError("The backup archive did not verify.")
        read = OrganizationArchiveReader().read(archive.data)
        inventory = OrganizationRestoreInventoryService().build(read)
        conflicts = await OrganizationRestoreConflictService(self.session).analyze(
            read, target_organization_id
        )
        if conflicts.conflicts:
            raise InvalidInputError(
                "The restore-test target is not ready: " + "; ".join(conflicts.conflicts)
            )
        restore = await OrganizationRestoreService(self.session, self.blobs).restore(
            archive.data, target_organization_id, requested_by_user_id, user_mappings
        )
        if restore.status is not OrganizationRestoreStatus.COMPLETED:
            raise ServiceUnavailableError("The restore-test restore did not complete.")
        summary: dict[str, object] = {
            "mode": DisasterRecoveryDrillMode.RESTORE_TEST.value,
            "archive_sha256": archive.sha256,
            "counts": inventory.counts,
            "asset_count": inventory.asset_count,
            "restore_id": str(restore.id),
            "restored": restore.summary.get("restored", {}),
        }
        return summary, restore
