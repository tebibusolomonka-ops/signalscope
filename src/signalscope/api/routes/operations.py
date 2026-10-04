import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from signalscope.api.dependencies import DatabaseSession
from signalscope.api.pagination import Page, Pagination
from signalscope.api.tenancy import Policy
from signalscope.domain.operations.access import operations_scope
from signalscope.domain.operations.attempt import OperationAttemptOutcome, OperationAttemptQueue
from signalscope.domain.operations.failed_jobs import FailedJobInspectionService
from signalscope.domain.operations.history import OperationHistoryService
from signalscope.domain.operations.latency import OperationLatencyService
from signalscope.domain.operations.overview import OrganizationOperationsService
from signalscope.domain.operations.queues import OperationsQueue
from signalscope.domain.operations.recovery import FailedJobRecoveryService
from signalscope.domain.operations.schemas import (
    JobRetryRequest,
    OperationAttemptRead,
    OperationsJobRead,
    OperationsOverviewRead,
    OperationTrendPointRead,
    OperationTrendsRead,
    QueueLatencyRead,
)
from signalscope.domain.operations.trends import OperationTrendService, TrendBucket

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


@router.get("/history")
async def operation_history(
    organization_id: OrganizationId,
    session: DatabaseSession,
    policy: Policy,
    page: Pagination,
    queue: OperationAttemptQueue | None = None,
    outcome: OperationAttemptOutcome | None = None,
    resource_type: Annotated[str | None, Query(max_length=32)] = None,
    resource_id: uuid.UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Page[OperationAttemptRead]:
    """Worker attempts of one organization, newest first."""
    items, total = await OperationHistoryService(session, policy).list_page(
        organization_id,
        queue=queue,
        outcome=outcome,
        resource_type=resource_type,
        resource_id=resource_id,
        created_from=created_from,
        created_to=created_to,
        limit=page.limit,
        offset=page.offset,
    )
    return Page[OperationAttemptRead](
        items=[OperationAttemptRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/trends")
async def operation_trends(
    organization_id: OrganizationId,
    session: DatabaseSession,
    policy: Policy,
    queue: OperationAttemptQueue | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    bucket: TrendBucket = TrendBucket.DAY,
) -> OperationTrendsRead:
    """Factual attempt-outcome buckets and latency summaries for one organization.

    Same access as the overview: owner or admin there, or a system admin. The
    organization filter is always applied, so there is no all-tenant view.
    """
    await operations_scope(policy, organization_id)
    queue_value = queue.value if queue is not None else None
    trends = await OperationTrendService(session).summarize(
        organization_id, queue=queue_value, start=created_from, end=created_to, bucket=bucket
    )
    latency = await OperationLatencyService(session).summarize(
        organization_id, queue=queue_value, start=created_from, end=created_to
    )
    return OperationTrendsRead(
        organization_id=organization_id,
        bucket=trends.bucket.value,
        points=[OperationTrendPointRead.model_validate(point) for point in trends.points],
        latency=[QueueLatencyRead.model_validate(summary) for summary in latency.queues],
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
