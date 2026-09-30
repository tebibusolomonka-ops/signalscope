import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query

from signalscope.api.auth import CurrentSession
from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.domain.audit.query import SecurityAuditQueryService
from signalscope.domain.audit.retention_service import AuditRetentionService
from signalscope.domain.audit.schemas import (
    AuditEventRead,
    RetentionCleanupRequest,
    RetentionCleanupResultRead,
    RetentionPolicyRead,
    RetentionPolicyWrite,
    RetentionPreviewRead,
)
from signalscope.domain.sources.scheduling import utc_now

router = APIRouter(prefix="/security", tags=["Security"])

ShortText = Annotated[str | None, Query(max_length=64)]

RetentionOrganizationId = Annotated[
    uuid.UUID,
    Query(description="The organization whose retention policy to use. Always required."),
]


def _utc(value: datetime | None) -> datetime | None:
    # A time without a zone is read as UTC.
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


@router.get("/audit")
async def list_audit_events(
    current: CurrentSession,
    session: DatabaseSession,
    page: Pagination,
    organization_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    action: ShortText = None,
    resource_type: ShortText = None,
    resource_id: uuid.UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Page[AuditEventRead]:
    """Security audit events, newest first.

    System admins see every event. Organization owners and admins must pass
    the organization_id of an organization they manage and see only its
    events. Members and viewers have no access (403). created_from is
    inclusive and created_to exclusive; times without a zone are UTC.
    """
    found, total = await SecurityAuditQueryService(session, current.user).query(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        created_from=_utc(created_from),
        created_to=_utc(created_to),
        limit=page.limit,
        offset=page.offset,
    )
    return Page[AuditEventRead](
        items=[AuditEventRead.build(item) for item in found],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/audit/retention")
async def get_audit_retention(
    organization_id: RetentionOrganizationId, current: CurrentSession, session: DatabaseSession
) -> RetentionPolicyRead:
    """One organization's security audit retention policy.

    Owners, admins and system admins may read it. Null days means events are
    kept for ever, which is the default when no policy is set.
    """
    view = await AuditRetentionService(session, current.user).get_policy(organization_id)
    return RetentionPolicyRead.model_validate(view)


@router.put("/audit/retention")
async def set_audit_retention(
    organization_id: RetentionOrganizationId,
    body: RetentionPolicyWrite,
    current: CurrentSession,
    session: DatabaseSession,
) -> RetentionPolicyRead:
    """Set one organization's security audit retention policy.

    Only a system admin may change it. Null days keeps events for ever;
    otherwise the value is bounded conservatively. The change is audited.
    """
    view = await AuditRetentionService(session, current.user).set_policy(
        organization_id, body.security_audit_days
    )
    return RetentionPolicyRead.model_validate(view)


@router.get("/audit/retention/preview")
async def preview_audit_retention(
    organization_id: RetentionOrganizationId, current: CurrentSession, session: DatabaseSession
) -> RetentionPreviewRead:
    """How many audit events a cleanup would remove now, without changing anything.

    Same access as reading the policy. Nothing is deletable when events are
    kept for ever.
    """
    preview = await AuditRetentionService(session, current.user).preview(organization_id, utc_now())
    return RetentionPreviewRead.model_validate(preview)


@router.post("/audit/retention/cleanup")
async def cleanup_audit_retention(
    organization_id: RetentionOrganizationId,
    body: RetentionCleanupRequest,
    current: CurrentSession,
    session: DatabaseSession,
) -> RetentionCleanupResultRead:
    """Delete the oldest audit events past the policy, bounded by limit.

    Only a system admin may run it. Nothing is deleted when events are kept
    for ever. A run that removes rows is itself audited.
    """
    result = await AuditRetentionService(session, current.user).cleanup(
        organization_id, utc_now(), body.limit
    )
    return RetentionCleanupResultRead.model_validate(result)
