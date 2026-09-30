import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ForbiddenError, InvalidInputError, NotFoundError
from signalscope.domain.audit.model import SecurityAuditEvent
from signalscope.domain.audit.retention import (
    MAX_SECURITY_AUDIT_DAYS,
    MIN_SECURITY_AUDIT_DAYS,
    OrganizationAuditRetentionPolicy,
)
from signalscope.domain.audit.service import AuditAction, DetailValue, SecurityAuditService
from signalscope.domain.organizations.membership import OrganizationMembership, OrganizationRole
from signalscope.domain.organizations.model import Organization
from signalscope.domain.users.model import User

MANAGER_ROLES = frozenset({OrganizationRole.OWNER, OrganizationRole.ADMIN})
ORGANIZATION_NOT_FOUND = "Organization was not found."
NO_RETENTION_ACCESS = "You do not have access to the audit retention policy."
ONLY_SYSTEM_ADMIN = "Only a system admin can change the policy or delete audit events."
DAYS_OUT_OF_RANGE = (
    f"security_audit_days must be from {MIN_SECURITY_AUDIT_DAYS} to {MAX_SECURITY_AUDIT_DAYS}, "
    "or empty to keep events for ever."
)


@dataclass(frozen=True, slots=True)
class RetentionPolicyView:
    """One organization's audit retention. None days keeps events for ever."""

    organization_id: uuid.UUID
    security_audit_days: int | None


@dataclass(frozen=True, slots=True)
class RetentionPreview:
    """What a cleanup would remove now, without changing anything.

    cutoff is None when events are kept for ever, and then nothing is
    deletable. deletable_count is not bounded by a cleanup limit.
    """

    organization_id: uuid.UUID
    security_audit_days: int | None
    cutoff: datetime | None
    deletable_count: int
    total_count: int


@dataclass(frozen=True, slots=True)
class CleanupResult:
    organization_id: uuid.UUID
    deleted: int


class AuditRetentionService:
    """Reads, sets and applies one organization's audit retention policy.

    The actor is the user asking, or None for a trusted server context such as
    the cleanup command. Owners, admins and system admins may read the policy
    and preview a cleanup. Only a system admin may change the policy or delete
    audit events; the server context may do everything. Setting the policy and
    a cleanup that removes rows are recorded in the security audit, without any
    event content. Writes commit before they return.
    """

    def __init__(self, session: AsyncSession, actor: User | None) -> None:
        self.session = session
        self.actor = actor

    async def get_policy(self, organization_id: uuid.UUID) -> RetentionPolicyView:
        await self._require_view(organization_id)
        return RetentionPolicyView(organization_id, await self._days(organization_id))

    async def set_policy(
        self, organization_id: uuid.UUID, security_audit_days: int | None
    ) -> RetentionPolicyView:
        await self._require_system_admin(organization_id)
        if security_audit_days is not None and not (
            MIN_SECURITY_AUDIT_DAYS <= security_audit_days <= MAX_SECURITY_AUDIT_DAYS
        ):
            raise InvalidInputError(DAYS_OUT_OF_RANGE)
        policy = await self.session.get(OrganizationAuditRetentionPolicy, organization_id)
        if policy is None:
            self.session.add(
                OrganizationAuditRetentionPolicy(
                    organization_id=organization_id, security_audit_days=security_audit_days
                )
            )
        else:
            policy.security_audit_days = security_audit_days
        self._record(
            AuditAction.AUDIT_RETENTION_SET, organization_id, {"retain_days": security_audit_days}
        )
        await self.session.commit()
        return RetentionPolicyView(organization_id, security_audit_days)

    async def preview(self, organization_id: uuid.UUID, now: datetime) -> RetentionPreview:
        await self._require_view(organization_id)
        days = await self._days(organization_id)
        cutoff = None if days is None else now - timedelta(days=days)
        total = await self.session.scalar(
            select(func.count()).where(SecurityAuditEvent.organization_id == organization_id)
        )
        deletable: int | None = 0
        if cutoff is not None:
            deletable = await self.session.scalar(
                select(func.count()).where(
                    SecurityAuditEvent.organization_id == organization_id,
                    SecurityAuditEvent.created_at < cutoff,
                )
            )
        return RetentionPreview(
            organization_id=organization_id,
            security_audit_days=days,
            cutoff=cutoff,
            deletable_count=deletable or 0,
            total_count=total or 0,
        )

    async def cleanup(self, organization_id: uuid.UUID, now: datetime, limit: int) -> CleanupResult:
        """Delete at most limit oldest events past the policy, and audit it.

        Nothing is deleted when the policy keeps events for ever. The delete is
        bounded by limit, so one run is always small; the caller repeats it
        until nothing is left. A run that removes rows records one audit event,
        which is never itself removed by the same run.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        await self._require_system_admin(organization_id)
        days = await self._days(organization_id)
        if days is None:
            return CleanupResult(organization_id, 0)
        cutoff = now - timedelta(days=days)
        oldest = (
            select(SecurityAuditEvent.id)
            .where(
                SecurityAuditEvent.organization_id == organization_id,
                SecurityAuditEvent.created_at < cutoff,
            )
            .order_by(SecurityAuditEvent.created_at, SecurityAuditEvent.id)
            .limit(limit)
        )
        result = await self.session.execute(
            delete(SecurityAuditEvent).where(SecurityAuditEvent.id.in_(oldest))
        )
        deleted = int(result.rowcount)  # type: ignore[attr-defined]
        if deleted:
            self._record(
                AuditAction.SECURITY_AUDIT_CLEANED,
                organization_id,
                {"deleted": deleted, "retain_days": days},
            )
        await self.session.commit()
        return CleanupResult(organization_id, deleted)

    async def _days(self, organization_id: uuid.UUID) -> int | None:
        policy = await self.session.get(OrganizationAuditRetentionPolicy, organization_id)
        return None if policy is None else policy.security_audit_days

    def _record(
        self, action: AuditAction, organization_id: uuid.UUID, details: dict[str, DetailValue]
    ) -> None:
        SecurityAuditService(self.session).record(
            action,
            actor_user_id=None if self.actor is None else self.actor.id,
            resource_type="organization",
            resource_id=organization_id,
            organization_id=organization_id,
            details=details,
        )

    async def _require_view(self, organization_id: uuid.UUID) -> None:
        if await self.session.get(Organization, organization_id) is None:
            raise NotFoundError(ORGANIZATION_NOT_FOUND)
        if self.actor is None or self.actor.is_system_admin:
            return
        membership = await self.session.get(
            OrganizationMembership, (organization_id, self.actor.id)
        )
        if membership is None:
            raise NotFoundError(ORGANIZATION_NOT_FOUND)
        if membership.role not in MANAGER_ROLES:
            raise ForbiddenError(NO_RETENTION_ACCESS)

    async def _require_system_admin(self, organization_id: uuid.UUID) -> None:
        await self._require_view(organization_id)
        if self.actor is not None and not self.actor.is_system_admin:
            raise ForbiddenError(ONLY_SYSTEM_ADMIN)
