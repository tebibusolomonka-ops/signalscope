import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.api.tenancy import Policy
from signalscope.domain.operations.failed_jobs import FailedJobInspectionService
from signalscope.domain.operations.overview import OrganizationOperationsService
from signalscope.domain.operations.queues import OperationsQueue
from signalscope.domain.operations.retry import FailedJobRetryService
from signalscope.domain.operations.schemas import (
    FailedJobRead,
    FailedJobRetryRequest,
    OperationsOverviewRead,
    RetriedJobRead,
)
from signalscope.domain.sources.scheduling import utc_now

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
) -> Page[FailedJobRead]:
    """Failed jobs of one organization, newest failure first, from one queue or all.

    Only failed jobs are listed; status is there to say so. Each job shows the
    record it works on and the short error stored when it failed. Same access
    as the overview.
    """
    items, total = await FailedJobInspectionService(session, policy).list_page(
        organization_id, queue, page.limit, page.offset
    )
    return Page[FailedJobRead](
        items=[FailedJobRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/jobs/retry")
async def retry_failed_job(
    organization_id: OrganizationId,
    request: FailedJobRetryRequest,
    session: DatabaseSession,
    policy: Policy,
) -> RetriedJobRead:
    """Put one failed job back in its queue.

    Needs authentication and the owner or admin role in the organization, or a
    system admin. Only a job that is still failed can be retried; the job
    becomes pending and available now, with its attempt count kept, so work
    that is already pending or running is never queued twice. A successful
    retry is recorded in the security audit, without any failure detail. The
    retry is refused (409) when the job is not failed, and not found (404)
    when the job is unknown or belongs to another organization.
    """
    retried = await FailedJobRetryService(session, policy).retry(
        organization_id, request.queue, request.job_id, utc_now()
    )
    return RetriedJobRead.model_validate(retried)
