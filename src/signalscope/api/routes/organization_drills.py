import uuid

from fastapi import APIRouter, status

from signalscope.api.auth import CurrentSession
from signalscope.api.dependencies import Blobs, DatabaseSession
from signalscope.api.pagination import Pagination
from signalscope.domain.organizations.drill_administration import (
    OrganizationDisasterRecoveryDrillAdministrationService,
)
from signalscope.domain.organizations.drill_schemas import (
    OrganizationDrillRead,
    OrganizationDrillRunRequest,
)

router = APIRouter(prefix="/organizations/{organization_id}", tags=["Organizations"])


@router.post("/drills", status_code=status.HTTP_201_CREATED)
async def run_organization_drill(
    organization_id: uuid.UUID,
    request: OrganizationDrillRunRequest,
    current: CurrentSession,
    session: DatabaseSession,
    blobs: Blobs,
) -> OrganizationDrillRead:
    drill = await OrganizationDisasterRecoveryDrillAdministrationService(
        session, current.user, blobs
    ).run(
        organization_id,
        mode=request.mode,
        target_organization_id=request.target_organization_id,
        include_assets=request.include_assets,
        user_mappings=request.user_mappings,
    )
    return OrganizationDrillRead.model_validate(drill)


@router.get("/drills")
async def list_organization_drills(
    organization_id: uuid.UUID,
    current: CurrentSession,
    session: DatabaseSession,
    page: Pagination,
) -> list[OrganizationDrillRead]:
    drills = await OrganizationDisasterRecoveryDrillAdministrationService(
        session, current.user
    ).list(organization_id, page.limit, page.offset)
    return [OrganizationDrillRead.model_validate(drill) for drill in drills]


@router.get("/drills/{drill_id}")
async def get_organization_drill(
    organization_id: uuid.UUID,
    drill_id: uuid.UUID,
    current: CurrentSession,
    session: DatabaseSession,
) -> OrganizationDrillRead:
    drill = await OrganizationDisasterRecoveryDrillAdministrationService(session, current.user).get(
        organization_id, drill_id
    )
    return OrganizationDrillRead.model_validate(drill)
