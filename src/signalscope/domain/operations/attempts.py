import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import short_error_message
from signalscope.domain.operations.attempt import (
    OperationAttempt,
    OperationAttemptOutcome,
    OperationAttemptQueue,
)


async def start_attempt(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID | None,
    queue: OperationAttemptQueue,
    job_id: uuid.UUID,
    attempt_number: int,
    resource_type: str,
    resource_id: uuid.UUID,
    started_at: datetime,
) -> None:
    """Record an organization-owned claim in the caller's transaction."""
    if organization_id is None:
        return
    session.add(
        OperationAttempt(
            organization_id=organization_id,
            queue_name=queue,
            job_id=job_id,
            attempt_number=attempt_number,
            resource_type=resource_type,
            resource_id=resource_id,
            started_at=started_at,
            outcome=OperationAttemptOutcome.RUNNING,
        )
    )


async def finish_attempt(
    session: AsyncSession,
    *,
    queue: OperationAttemptQueue,
    job_id: uuid.UUID,
    attempt_number: int,
    outcome: OperationAttemptOutcome,
    finished_at: datetime,
    error: str | None = None,
) -> None:
    attempt = await session.scalar(
        select(OperationAttempt)
        .where(
            OperationAttempt.queue_name == queue,
            OperationAttempt.job_id == job_id,
            OperationAttempt.attempt_number == attempt_number,
            OperationAttempt.outcome == OperationAttemptOutcome.RUNNING,
        )
        .with_for_update()
    )
    if attempt is None:
        return
    attempt.outcome = outcome
    attempt.finished_at = finished_at
    attempt.safe_error = None if error is None else short_error_message(error)
