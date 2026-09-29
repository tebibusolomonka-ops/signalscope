import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query

from signalscope.api.auth import CurrentSession
from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.domain.audit.query import SecurityAuditQueryService
from signalscope.domain.audit.schemas import AuditEventRead

router = APIRouter(prefix="/security", tags=["Security"])

ShortText = Annotated[str | None, Query(max_length=64)]


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
