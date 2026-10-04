import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body

from signalscope.api.auth import CurrentSession
from signalscope.api.dependencies import DatabaseSession
from signalscope.core.errors import ForbiddenError
from signalscope.domain.organizations.restore_plan import build_restore_plan

router = APIRouter(prefix="/organizations", tags=["Organization restore planning"])


@router.post("/{organization_id}/restore-plan")
async def plan_organization_restore(
    organization_id: uuid.UUID,
    archive: Annotated[bytes, Body(media_type="application/zip")],
    current: CurrentSession,
    session: DatabaseSession,
) -> dict[str, Any]:
    """Verify and plan an organization restore without changing data."""
    if not current.user.is_system_admin:
        raise ForbiddenError("Only system admins can plan organization restores.")
    return await build_restore_plan(session, archive, organization_id)
