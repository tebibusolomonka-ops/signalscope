import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import (
    ConflictError,
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
)
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.audit.service import AuditAction, SecurityAuditService
from signalscope.domain.organizations.membership import OrganizationMembership, OrganizationRole
from signalscope.domain.organizations.model import Organization
from signalscope.domain.retention.model import (
    MAX_SECURITY_AUDIT_DAYS,
    MIN_SECURITY_AUDIT_DAYS,
    OrganizationRetentionPolicy,
)
from signalscope.domain.sources.scheduling import Clock, utc_now
from signalscope.domain.users.model import User

ORGANIZATION_NOT_FOUND = "Organization was not found."
VIEW_ROLES = frozenset({OrganizationRole.OWNER, OrganizationRole.ADMIN})
SYSTEM_ADMIN_ONLY = "Only system admins can change audit retention or delete audit events."
NO_POLICY = "This organization keeps its audit events indefinitely, so nothing is deleted."


@dataclass(frozen=True, slots=True)
class RetentionPolicyView:
    organization_id: uuid.UUID
    # None: security audit events are kept indefinitely.
    security_audit_days: int | None
    # None when no policy was ever set.
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class AuditRetentionPreview:
    organization_id: uuid.UUID
    retention_days: int | None
    # Events created before this are eligible. None without a policy.
    cutoff: datetime | None
    eligible_count: int


@dataclass(frozen=True, slots=True)
class AuditCleanupResult:
    organization_id: uuid.UUID
    retention_days: int
    cutoff: datetime
    deleted_count: int


class AuditRetentionService:
    """Audit retention of one organization.

    Organization owners and admins, and system admins, may read the policy
    and preview what it would delete. Only system admins set it or delete
    events, so an organization cannot quietly erase its own audit history.
    actor None is the local command line, which is trusted like a system
    admin; the API always passes a signed in user.

    Only events of the organization are touched. Events without an
    organization, such as logins, are never deleted here.
    """

    def __init__(self, session: AsyncSession, clock: Clock = utc_now) -> None:
        self.session = session
        self.clock = clock

    async def get_policy(
        self, actor: User | None, organization_id: uuid.UUID
    ) -> RetentionPolicyView:
        await self._check_view(actor, organization_id)
        return self._view(organization_id, await self._policy(organization_id))

    async def set_policy(
        self, actor: User | None, organization_id: uuid.UUID, security_audit_days: int | None
    ) -> RetentionPolicyView:
        await self._check_change(actor, organization_id)
        if security_audit_days is not None and not (
            MIN_SECURITY_AUDIT_DAYS <= security_audit_days <= MAX_SECURITY_AUDIT_DAYS
        ):
            raise InvalidInputError(
                f"security_audit_days must be between {MIN_SECURITY_AUDIT_DAYS} "
                f"and {MAX_SECURITY_AUDIT_DAYS}, or null to keep events indefinitely."
            )
        try:
            policy = await self._policy(organization_id, lock=True)
            if policy is None:
                policy = OrganizationRetentionPolicy(organization_id=organization_id)
                self.session.add(policy)
            policy.security_audit_days = security_audit_days
            SecurityAuditService(self.session).record(
                AuditAction.AUDIT_RETENTION_CHANGED,
                actor_user_id=None if actor is None else actor.id,
                resource_type="organization",
                resource_id=organization_id,
                organization_id=organization_id,
                details={"retention_days": security_audit_days},
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return self._view(organization_id, policy)

    async def preview(
        self, actor: User | None, organization_id: uuid.UUID
    ) -> AuditRetentionPreview:
        await self._check_view(actor, organization_id)
        policy = await self._policy(organization_id)
        days = None if policy is None else policy.security_audit_days
        if days is None:
            return AuditRetentionPreview(organization_id, None, None, 0)
        cutoff = self.clock() - timedelta(days=days)
        eligible = await self.session.scalar(
            select(func.count())
            .select_from(SecurityAuditEvent)
            .where(*_eligible(organization_id, cutoff))
        )
        return AuditRetentionPreview(organization_id, days, cutoff, eligible or 0)

    async def cleanup(
        self, actor: User | None, organization_id: uuid.UUID, limit: int
    ) -> AuditCleanupResult:
        """Delete at most limit eligible events, oldest first, and record that it happened.

        The deletion and its own audit event are committed together. The new
        event is created now, so it is never eligible under the same policy.
        """
        if limit < 1:
            raise InvalidInputError("limit must be at least 1.")
        await self._check_change(actor, organization_id)
        try:
            policy = await self._policy(organization_id, lock=True)
            days = None if policy is None else policy.security_audit_days
            if days is None:
                raise ConflictError(NO_POLICY)
            cutoff = self.clock() - timedelta(days=days)
            oldest = (
                select(SecurityAuditEvent.id)
                .where(*_eligible(organization_id, cutoff))
                .order_by(SecurityAuditEvent.created_at, SecurityAuditEvent.id)
                .limit(limit)
            )
            deleted = await self.session.scalars(
                delete(SecurityAuditEvent)
                .where(SecurityAuditEvent.id.in_(oldest))
                .returning(SecurityAuditEvent.id)
                .execution_options(synchronize_session=False)
            )
            deleted_count = len(deleted.all())
            SecurityAuditService(self.session).record(
                AuditAction.AUDIT_RETENTION_CLEANUP,
                actor_user_id=None if actor is None else actor.id,
                resource_type="organization",
                resource_id=organization_id,
                organization_id=organization_id,
                details={"deleted_count": deleted_count, "retention_days": days},
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return AuditCleanupResult(organization_id, days, cutoff, deleted_count)

    async def _policy(
        self, organization_id: uuid.UUID, lock: bool = False
    ) -> OrganizationRetentionPolicy | None:
        statement = select(OrganizationRetentionPolicy).where(
            OrganizationRetentionPolicy.organization_id == organization_id
        )
        if lock:
            statement = statement.with_for_update()
        policy: OrganizationRetentionPolicy | None = await self.session.scalar(statement)
        return policy

    async def _check_view(self, actor: User | None, organization_id: uuid.UUID) -> None:
        if await self.session.get(Organization, organization_id) is None:
            raise NotFoundError(ORGANIZATION_NOT_FOUND)
        if actor is None or actor.is_system_admin:
            return
        membership = await self.session.get(OrganizationMembership, (organization_id, actor.id))
        if membership is None:
            raise NotFoundError(ORGANIZATION_NOT_FOUND)
        if membership.role not in VIEW_ROLES:
            raise ForbiddenError("Only organization owners and admins can see audit retention.")

    async def _check_change(self, actor: User | None, organization_id: uuid.UUID) -> None:
        await self._check_view(actor, organization_id)
        if actor is not None and not actor.is_system_admin:
            raise ForbiddenError(SYSTEM_ADMIN_ONLY)

    @staticmethod
    def _view(
        organization_id: uuid.UUID, policy: OrganizationRetentionPolicy | None
    ) -> RetentionPolicyView:
        if policy is None:
            return RetentionPolicyView(organization_id, None, None)
        return RetentionPolicyView(organization_id, policy.security_audit_days, policy.updated_at)


def _eligible(
    organization_id: uuid.UUID, cutoff: datetime
) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    return (
        SecurityAuditEvent.organization_id == organization_id,
        SecurityAuditEvent.created_at < cutoff,
    )
