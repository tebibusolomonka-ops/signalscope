import uuid

from fastapi import APIRouter

from signalscope.api.auth import CurrentSession
from signalscope.api.dependencies import DatabaseSession
from signalscope.core.errors import InvalidInputError
from signalscope.domain.retention.schemas import (
    AuditCleanupRead,
    AuditCleanupRequest,
    AuditRetentionPreviewRead,
    RetentionPolicyRead,
    RetentionPolicyUpdate,
)
from signalscope.domain.retention.service import AuditRetentionService

router = APIRouter(prefix="/organizations", tags=["Retention"])


@router.get("/{organization_id}/retention")
async def get_retention(
    organization_id: uuid.UUID, current: CurrentSession, session: DatabaseSession
) -> RetentionPolicyRead:
    """The organization's retention policy. Without one, audit events are kept indefinitely.

    Organization owners, admins and system admins.
    """
    policy = await AuditRetentionService(session).get_policy(current.user, organization_id)
    return RetentionPolicyRead.model_validate(policy)


@router.put("/{organization_id}/retention")
async def set_retention(
    organization_id: uuid.UUID,
    request: RetentionPolicyUpdate,
    current: CurrentSession,
    session: DatabaseSession,
) -> RetentionPolicyRead:
    """Set how many days security audit events are kept (30 to 3650), or null for indefinitely.

    System admins only. Nothing is deleted here; see audit-cleanup. The change
    is recorded in the security audit log.
    """
    policy = await AuditRetentionService(session).set_policy(
        current.user, organization_id, request.security_audit_days
    )
    return RetentionPolicyRead.model_validate(policy)


@router.get("/{organization_id}/retention/audit-preview")
async def preview_audit_retention(
    organization_id: uuid.UUID, current: CurrentSession, session: DatabaseSession
) -> AuditRetentionPreviewRead:
    """How many of the organization's audit events the policy makes eligible for deletion.

    Organization owners, admins and system admins. Events without an
    organization are never counted.
    """
    preview = await AuditRetentionService(session).preview(current.user, organization_id)
    return AuditRetentionPreviewRead.model_validate(preview)


@router.post("/{organization_id}/retention/audit-cleanup")
async def cleanup_audit_retention(
    organization_id: uuid.UUID,
    request: AuditCleanupRequest,
    current: CurrentSession,
    session: DatabaseSession,
) -> AuditCleanupRead:
    """Delete at most limit eligible audit events of the organization, oldest first.

    System admins only, with "confirm": true. Without a policy nothing is
    deleted (409). The cleanup itself is recorded as a new audit event.
    """
    if not request.confirm:
        raise InvalidInputError("Set confirm to true to delete audit events.")
    result = await AuditRetentionService(session).cleanup(
        current.user, organization_id, request.limit
    )
    return AuditCleanupRead.model_validate(result)
