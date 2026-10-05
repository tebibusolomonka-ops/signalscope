import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import (
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
    ServiceUnavailableError,
)
from signalscope.domain.audit.service import AuditAction, SecurityAuditService
from signalscope.domain.organizations.backup_policy import (
    MAX_BACKUP_RETENTION_COUNT,
    MIN_BACKUP_RETENTION_COUNT,
    OrganizationBackupFrequency,
    OrganizationBackupPolicy,
)
from signalscope.domain.organizations.backup_service import (
    BACKUP_ARTIFACT_PREFIX,
    OrganizationBackupService,
)
from signalscope.domain.organizations.export_record import OrganizationExport
from signalscope.domain.organizations.membership import OrganizationMembership, OrganizationRole
from signalscope.domain.organizations.model import Organization
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.domain.users.model import User
from signalscope.storage.blob import BlobStore

BACKUP_ROLES = frozenset({OrganizationRole.OWNER, OrganizationRole.ADMIN})


@dataclass(frozen=True, slots=True)
class OrganizationBackupPolicyView:
    organization_id: uuid.UUID
    enabled: bool
    frequency: OrganizationBackupFrequency
    retention_count: int
    include_assets: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    updated_at: datetime | None


class OrganizationBackupAdministrationService:
    """Manage backup policy and runs for organization administrators."""

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

    async def get_policy(self, organization_id: uuid.UUID) -> OrganizationBackupPolicyView:
        await self._authorize(organization_id)
        return self._view(
            organization_id, await self.session.get(OrganizationBackupPolicy, organization_id)
        )

    async def set_policy(
        self,
        organization_id: uuid.UUID,
        *,
        enabled: bool,
        frequency: OrganizationBackupFrequency,
        retention_count: int,
        include_assets: bool,
    ) -> OrganizationBackupPolicyView:
        await self._authorize(organization_id)
        if not MIN_BACKUP_RETENTION_COUNT <= retention_count <= MAX_BACKUP_RETENTION_COUNT:
            raise InvalidInputError(
                f"retention_count must be between {MIN_BACKUP_RETENTION_COUNT} "
                f"and {MAX_BACKUP_RETENTION_COUNT}."
            )
        policy = await self.session.scalar(
            select(OrganizationBackupPolicy)
            .where(OrganizationBackupPolicy.organization_id == organization_id)
            .with_for_update()
        )
        if policy is None:
            policy = OrganizationBackupPolicy(organization_id=organization_id)
            self.session.add(policy)
        schedule_changed = not policy.enabled or policy.frequency is not frequency
        policy.enabled = enabled
        policy.frequency = frequency
        policy.retention_count = retention_count
        policy.include_assets = include_assets
        if not enabled:
            policy.next_run_at = None
        elif schedule_changed or policy.next_run_at is None:
            policy.next_run_at = self.clock()
        SecurityAuditService(self.session).record(
            AuditAction.ORGANIZATION_BACKUP_POLICY_CHANGED,
            actor_user_id=self.actor.id,
            organization_id=organization_id,
            resource_type="organization_backup_policy",
            resource_id=organization_id,
        )
        await self.session.commit()
        return self._view(organization_id, policy)

    async def run(self, organization_id: uuid.UUID) -> OrganizationExport:
        await self._authorize(organization_id)
        if self.blobs is None:
            raise ServiceUnavailableError("File storage is not configured.")
        SecurityAuditService(self.session).record(
            AuditAction.ORGANIZATION_BACKUP_RUN,
            actor_user_id=self.actor.id,
            organization_id=organization_id,
            resource_type="organization_backup",
            resource_id=organization_id,
        )
        return await OrganizationBackupService(
            self.session,
            self.blobs,
            self.clock,
            self.max_assets,
            self.max_bytes,
        ).run(organization_id, self.actor.id)

    async def list(
        self, organization_id: uuid.UUID, limit: int, offset: int
    ) -> list[OrganizationExport]:
        await self._authorize(organization_id)
        exports = await self.session.scalars(
            select(OrganizationExport)
            .where(
                OrganizationExport.organization_id == organization_id,
                OrganizationExport.artifact_key.startswith(BACKUP_ARTIFACT_PREFIX),
            )
            .order_by(OrganizationExport.created_at.desc(), OrganizationExport.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(exports)

    async def _authorize(self, organization_id: uuid.UUID) -> None:
        if await self.session.get(Organization, organization_id) is None:
            raise NotFoundError("Organization was not found.")
        if self.actor.is_system_admin:
            return
        membership = await self.session.get(
            OrganizationMembership, (organization_id, self.actor.id)
        )
        if membership is None:
            raise NotFoundError("Organization was not found.")
        if membership.role not in BACKUP_ROLES:
            raise ForbiddenError("Only organization owners and admins can manage backups.")

    @staticmethod
    def _view(
        organization_id: uuid.UUID, policy: OrganizationBackupPolicy | None
    ) -> OrganizationBackupPolicyView:
        if policy is None:
            return OrganizationBackupPolicyView(
                organization_id=organization_id,
                enabled=False,
                frequency=OrganizationBackupFrequency.DAILY,
                retention_count=7,
                include_assets=False,
                last_run_at=None,
                next_run_at=None,
                updated_at=None,
            )
        return OrganizationBackupPolicyView(
            organization_id=organization_id,
            enabled=policy.enabled,
            frequency=policy.frequency,
            retention_count=policy.retention_count,
            include_assets=policy.include_assets,
            last_run_at=policy.last_run_at,
            next_run_at=policy.next_run_at,
            updated_at=policy.updated_at,
        )
