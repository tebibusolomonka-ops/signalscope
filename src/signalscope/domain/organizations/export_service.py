import uuid
from contextlib import suppress
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import (
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    SignalScopeError,
    short_error_message,
)
from signalscope.domain.audit.service import AuditAction, SecurityAuditService
from signalscope.domain.documents.asset import DocumentAsset
from signalscope.domain.documents.model import Document
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
    OrganizationExportVerification,
    OrganizationExportVerificationService,
)
from signalscope.domain.organizations.membership import OrganizationMembership, OrganizationRole
from signalscope.domain.organizations.model import Organization
from signalscope.domain.sources.model import Source
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.domain.users.model import User
from signalscope.storage.blob import BlobStore

EXPORT_ROLES = frozenset({OrganizationRole.OWNER, OrganizationRole.ADMIN})


@dataclass(frozen=True, slots=True)
class OrganizationExportAssets:
    asset_count: int
    asset_bytes: int


class OrganizationExportService:
    """Create and administer portable exports for owners and administrators."""

    def __init__(
        self,
        session: AsyncSession,
        actor: User,
        blobs: BlobStore | None = None,
        clock: Clock = utc_now,
        max_assets: int = 10_000,
        max_bytes: int = 500_000_000,
    ) -> None:
        self.session = session
        self.actor = actor
        self.blobs = blobs
        self.clock = clock
        self.max_assets = max_assets
        self.max_bytes = max_bytes

    async def create(self, organization_id: uuid.UUID) -> OrganizationExport:
        await self._authorize(organization_id)
        if self.blobs is None:
            raise ServiceUnavailableError("File storage is not configured.")
        now = self.clock()
        actor_id = self.actor.id
        export = OrganizationExport(
            organization_id=organization_id,
            requested_by_user_id=actor_id,
            status=OrganizationExportStatus.RUNNING,
            format_version=EXPORT_FORMAT_VERSION,
            started_at=now,
        )
        self.session.add(export)
        await self.session.flush()
        export.artifact_key = f"organization-exports/{export.id}.zip"
        export_id = export.id
        artifact_key = export.artifact_key
        try:
            archive = await OrganizationExportArchiveService(
                OrganizationExportInventoryService(self.session),
                self.blobs,
                self.clock,
                self.max_assets,
                self.max_bytes,
            ).store(organization_id, export.artifact_key)
            export.status = OrganizationExportStatus.COMPLETED
            export.finished_at = self.clock()
            export.size_bytes = archive.size_bytes
            export.sha256 = archive.sha256
            SecurityAuditService(self.session).record(
                AuditAction.ORGANIZATION_EXPORT_CREATED,
                actor_user_id=actor_id,
                organization_id=organization_id,
                resource_type="organization_export",
                resource_id=export.id,
            )
            await self.session.commit()
        except Exception as error:
            await self.session.rollback()
            if artifact_key is not None:
                with suppress(SignalScopeError):
                    await self.blobs.delete(artifact_key)
            failed = OrganizationExport(
                id=export_id,
                organization_id=organization_id,
                requested_by_user_id=actor_id,
                status=OrganizationExportStatus.FAILED,
                format_version=EXPORT_FORMAT_VERSION,
                started_at=now,
                finished_at=self.clock(),
                safe_error=_safe_error(error),
            )
            self.session.add(failed)
            await self.session.commit()
            return failed
        return export

    async def list(self, organization_id: uuid.UUID) -> list[OrganizationExport]:
        await self._authorize(organization_id)
        exports = await self.session.scalars(
            select(OrganizationExport)
            .where(OrganizationExport.organization_id == organization_id)
            .order_by(OrganizationExport.created_at.desc(), OrganizationExport.id.desc())
        )
        return list(exports)

    async def assets(self, organization_id: uuid.UUID) -> OrganizationExportAssets:
        await self._authorize(organization_id)
        row = (
            await self.session.execute(
                select(
                    func.count(DocumentAsset.id),
                    func.coalesce(func.sum(DocumentAsset.size_bytes), 0),
                )
                .select_from(DocumentAsset)
                .join(Document, Document.id == DocumentAsset.document_id)
                .join(Source, Source.id == Document.source_id)
                .where(Source.organization_id == organization_id)
            )
        ).one()
        return OrganizationExportAssets(asset_count=int(row[0]), asset_bytes=int(row[1]))

    async def get(self, organization_id: uuid.UUID, export_id: uuid.UUID) -> OrganizationExport:
        await self._authorize(organization_id)
        export = await self.session.get(OrganizationExport, export_id)
        if export is None or export.organization_id != organization_id:
            raise NotFoundError("Organization export was not found.")
        return export

    async def download(self, organization_id: uuid.UUID, export_id: uuid.UUID) -> bytes:
        export = await self.get(organization_id, export_id)
        if export.status is not OrganizationExportStatus.COMPLETED or export.artifact_key is None:
            raise NotFoundError("Organization export artifact was not found.")
        if self.blobs is None:
            raise ServiceUnavailableError("File storage is not configured.")
        return await self.blobs.get(export.artifact_key)

    async def verify(
        self, organization_id: uuid.UUID, export_id: uuid.UUID
    ) -> OrganizationExportVerification:
        data = await self.download(organization_id, export_id)
        return OrganizationExportVerificationService().verify(data)

    async def _authorize(self, organization_id: uuid.UUID) -> Organization:
        organization = await self.session.get(Organization, organization_id)
        if organization is None:
            raise NotFoundError("Organization was not found.")
        if self.actor.is_system_admin:
            return organization
        membership = await self.session.get(
            OrganizationMembership, (organization_id, self.actor.id)
        )
        if membership is None:
            raise NotFoundError("Organization was not found.")
        if membership.role not in EXPORT_ROLES:
            raise ForbiddenError("Only organization owners and admins can manage exports.")
        return organization


def _safe_error(error: Exception) -> str:
    if isinstance(error, SignalScopeError):
        return short_error_message(str(error))
    return "Export generation failed."
