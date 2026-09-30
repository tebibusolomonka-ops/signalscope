import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from signalscope.api.dependencies import DatabaseSession
from signalscope.api.tenancy import Policy
from signalscope.domain.operations.overview import OrganizationOperationsService
from signalscope.domain.operations.schemas import OperationsOverviewRead

router = APIRouter(prefix="/operations", tags=["Operations"])

OrganizationId = Annotated[
    uuid.UUID,
    Query(description="The organization whose jobs to show. Required, also for system admins."),
]


@router.get("/overview")
async def operations_overview(
    organization_id: OrganizationId, session: DatabaseSession, policy: Policy
) -> OperationsOverviewRead:
    """Pending, running and failed jobs per queue for one organization.

    Needs authentication and the owner or admin role there, or a system admin.
    States are shown as stored: a running job whose lease ran out still counts
    as running until a worker puts it back in the queue.
    """
    overview = await OrganizationOperationsService(session, policy).overview(organization_id)
    return OperationsOverviewRead.model_validate(overview)
