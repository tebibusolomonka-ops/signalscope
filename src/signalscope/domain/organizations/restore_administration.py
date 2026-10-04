import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import (
    ForbiddenError,
    InvalidInputError,
    ServiceUnavailableError,
    SignalScopeError,
)
from signalscope.domain.audit.service import AuditAction, SecurityAuditService
from signalscope.domain.organizations.restore_plan import build_restore_plan
from signalscope.domain.organizations.restore_record import OrganizationRestore
from signalscope.domain.organizations.restore_service import (
    MAX_RESTORE_RECORDS,
    OrganizationRestoreService,
)
from signalscope.domain.users.model import User
from signalscope.storage.blob import BlobStore


class OrganizationRestoreAdministrationService:
    """System-admin restore planning and application, with audit records."""

    def __init__(
        self,
        session: AsyncSession,
        user: User,
        blobs: BlobStore | None = None,
        *,
        max_records: int = MAX_RESTORE_RECORDS,
    ) -> None:
        self.session = session
        self.user = user
        self.blobs = blobs
        self.max_records = max_records

    async def plan(self, data: bytes, target_organization_id: uuid.UUID | None) -> dict[str, Any]:
        self._require_admin()
        return await build_restore_plan(self.session, data, target_organization_id)

    async def apply(
        self,
        data: bytes,
        target_organization_id: uuid.UUID,
        user_mappings: Mapping[str, uuid.UUID],
        *,
        confirmed: bool,
    ) -> OrganizationRestore:
        self._require_admin()
        if not confirmed:
            raise InvalidInputError("Organization restore must be confirmed.")
        if self.blobs is None:
            raise ServiceUnavailableError("File storage is not configured.")
        audit = SecurityAuditService(self.session)
        try:
            restore = await OrganizationRestoreService(
                self.session, self.blobs, max_records=self.max_records
            ).restore(data, target_organization_id, self.user.id, user_mappings)
        except SignalScopeError:
            self._record(audit, target_organization_id, None, "failed")
            await self.session.commit()
            raise
        self._record(audit, target_organization_id, restore.id, restore.status.value)
        await self.session.commit()
        return restore

    def _record(
        self,
        audit: SecurityAuditService,
        organization_id: uuid.UUID,
        restore_id: uuid.UUID | None,
        outcome: str,
    ) -> None:
        audit.record(
            AuditAction.ORGANIZATION_RESTORE_RUN,
            actor_user_id=self.user.id,
            organization_id=organization_id,
            resource_type="organization_restore",
            resource_id=restore_id,
            details={"reason": outcome},
        )

    def _require_admin(self) -> None:
        if not self.user.is_system_admin:
            raise ForbiddenError("Only system admins can restore organizations.")
