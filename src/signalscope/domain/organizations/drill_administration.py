import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ForbiddenError, NotFoundError, ServiceUnavailableError
from signalscope.domain.audit.service import AuditAction, SecurityAuditService
from signalscope.domain.organizations.drill_record import (
    DisasterRecoveryDrillMode,
    OrganizationDisasterRecoveryDrill,
)
from signalscope.domain.organizations.drill_service import (
    OrganizationDisasterRecoveryDrillService,
)
from signalscope.domain.organizations.membership import OrganizationMembership, OrganizationRole
from signalscope.domain.organizations.model import Organization
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.domain.users.model import User
from signalscope.storage.blob import BlobStore

DRILL_ROLES = frozenset({OrganizationRole.OWNER, OrganizationRole.ADMIN})


class OrganizationDisasterRecoveryDrillAdministrationService:
    """Run and read disaster-recovery drills for organization administrators.

    Owners, admins and system admins may run verification-only drills. A
    restore-test drill changes a separate target organization, so it requires a
    system admin.
    """

    def __init__(
        self,
        session: AsyncSession,
        actor: User,
        blobs: BlobStore | None = None,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self.session = session
        self.actor = actor
        self.blobs = blobs
        self.clock = clock

    async def run(
        self,
        organization_id: uuid.UUID,
        *,
        mode: DisasterRecoveryDrillMode,
        target_organization_id: uuid.UUID | None = None,
        include_assets: bool = True,
        user_mappings: Mapping[str, uuid.UUID] | None = None,
    ) -> OrganizationDisasterRecoveryDrill:
        await self._authorize(organization_id, mode)
        if self.blobs is None:
            raise ServiceUnavailableError("File storage is not configured.")
        audit = SecurityAuditService(self.session)
        audit.record(
            AuditAction.ORGANIZATION_DR_DRILL_RUN,
            actor_user_id=self.actor.id,
            organization_id=organization_id,
            resource_type="organization_disaster_recovery_drill",
            details={"reason": "started"},
        )
        drill = await OrganizationDisasterRecoveryDrillService(
            self.session, self.blobs, clock=self.clock
        ).run(
            organization_id,
            self.actor.id,
            mode=mode,
            target_organization_id=target_organization_id,
            include_assets=include_assets,
            user_mappings=user_mappings,
        )
        audit.record(
            AuditAction.ORGANIZATION_DR_DRILL_RUN,
            actor_user_id=self.actor.id,
            organization_id=organization_id,
            resource_type="organization_disaster_recovery_drill",
            resource_id=drill.id,
            details={"reason": drill.status.value},
        )
        await self.session.commit()
        return drill

    async def list(
        self, organization_id: uuid.UUID, limit: int, offset: int
    ) -> list[OrganizationDisasterRecoveryDrill]:
        await self._authorize(organization_id, DisasterRecoveryDrillMode.VERIFICATION_ONLY)
        drills = await self.session.scalars(
            select(OrganizationDisasterRecoveryDrill)
            .where(OrganizationDisasterRecoveryDrill.organization_id == organization_id)
            .order_by(
                OrganizationDisasterRecoveryDrill.created_at.desc(),
                OrganizationDisasterRecoveryDrill.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(drills)

    async def get(
        self, organization_id: uuid.UUID, drill_id: uuid.UUID
    ) -> OrganizationDisasterRecoveryDrill:
        await self._authorize(organization_id, DisasterRecoveryDrillMode.VERIFICATION_ONLY)
        drill = await self.session.get(OrganizationDisasterRecoveryDrill, drill_id)
        if drill is None or drill.organization_id != organization_id:
            raise NotFoundError("Disaster recovery drill was not found.")
        return drill

    async def _authorize(self, organization_id: uuid.UUID, mode: DisasterRecoveryDrillMode) -> None:
        if await self.session.get(Organization, organization_id) is None:
            raise NotFoundError("Organization was not found.")
        if mode is DisasterRecoveryDrillMode.RESTORE_TEST and not self.actor.is_system_admin:
            raise ForbiddenError("Only system admins can run restore-test drills.")
        if self.actor.is_system_admin:
            return
        membership = await self.session.get(
            OrganizationMembership, (organization_id, self.actor.id)
        )
        if membership is None:
            raise NotFoundError("Organization was not found.")
        if membership.role not in DRILL_ROLES:
            raise ForbiddenError(
                "Only organization owners and admins can run disaster recovery drills."
            )
