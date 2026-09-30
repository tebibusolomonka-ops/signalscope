import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.api.tenancy import Policy
from signalscope.domain.operations.failed_jobs import FailedJobInspectionService
from signalscope.domain.operations.overview import OrganizationOperationsService
from signalscope.domain.operations.queues import OperationsQueue
from signalscope.domain.operations.recovery import FailedJobRecoveryService
from signalscope.domain.operations.schemas import (
    JobRetryRequest,
    OperationsJobRead,
    OperationsOverviewRead,
)

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


@router.get("/jobs")
async def failed_jobs(
    organization_id: OrganizationId,
    session: DatabaseSession,
    policy: Policy,
    page: Pagination,
    queue: OperationsQueue | None = None,
    status: Literal["failed"] = "failed",
) -> Page[OperationsJobRead]:
    """Failed jobs of one organization, newest failure first, from one queue or all.

    Only failed jobs are listed; status is there to say so. Each job shows the
    record it works on and the short error stored when it failed. Same access
    as the overview.
    """
    items, total = await FailedJobInspectionService(session, policy).list_page(
        organization_id, queue, page.limit, page.offset
    )
    return Page[OperationsJobRead](
        items=[OperationsJobRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/jobs/{queue}/{job_id}/retry")
async def retry_failed_job(
    queue: OperationsQueue,
    job_id: uuid.UUID,
    request: JobRetryRequest,
    session: DatabaseSession,
    policy: Policy,
) -> OperationsJobRead:
    """Put a failed job of the organization back in its queue, available now.

    Each queue is retried its own way: chunk jobs whose results are already
    current are refused, and a failed ingestion gets a new run. The attempt
    count is kept. A job of another organization is not found; a job that is
    not failed, or work that is current or already queued, answers 409. The
    retry is recorded in the security audit log. Same access as the overview.
    """
    job = await FailedJobRecoveryService(session, policy).retry(
        request.organization_id, queue, job_id
    )
    return OperationsJobRead.model_validate(job)
