import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.operations.attempt import OperationAttempt, OperationAttemptOutcome


class TrendBucket(StrEnum):
    HOUR = "hour"
    DAY = "day"


@dataclass(frozen=True, slots=True)
class OperationTrendPoint:
    bucket_start: datetime
    total: int
    succeeded: int
    failed: int
    recovered: int
    running: int
    retried: int


@dataclass(frozen=True, slots=True)
class OperationTrendReport:
    organization_id: uuid.UUID
    bucket: TrendBucket
    points: tuple[OperationTrendPoint, ...]


class OperationTrendService:
    """Factual time-bucketed counts of operation attempts for one organization.

    The organization filter is always applied before aggregation, so counts
    never mix tenants. No subjective health score is produced.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summarize(
        self,
        organization_id: uuid.UUID,
        *,
        queue: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        bucket: TrendBucket = TrendBucket.DAY,
    ) -> OperationTrendReport:
        bucket_start = func.date_trunc(bucket.value, OperationAttempt.created_at)
        conditions = [OperationAttempt.organization_id == organization_id]
        if queue is not None:
            conditions.append(OperationAttempt.queue_name == queue)
        if start is not None:
            conditions.append(OperationAttempt.created_at >= start)
        if end is not None:
            conditions.append(OperationAttempt.created_at < end)

        rows = await self.session.execute(
            select(
                bucket_start.label("bucket_start"),
                func.count().label("total"),
                _count_when(OperationAttemptOutcome.SUCCEEDED).label("succeeded"),
                _count_when(OperationAttemptOutcome.FAILED).label("failed"),
                _count_when(OperationAttemptOutcome.RECOVERED).label("recovered"),
                _count_when(OperationAttemptOutcome.RUNNING).label("running"),
                func.sum(case((OperationAttempt.attempt_number > 1, 1), else_=0)).label("retried"),
            )
            .where(*conditions)
            .group_by(bucket_start)
            .order_by(bucket_start)
        )
        points = tuple(
            OperationTrendPoint(
                bucket_start=row.bucket_start,
                total=row.total,
                succeeded=row.succeeded or 0,
                failed=row.failed or 0,
                recovered=row.recovered or 0,
                running=row.running or 0,
                retried=row.retried or 0,
            )
            for row in rows
        )
        return OperationTrendReport(organization_id=organization_id, bucket=bucket, points=points)


def _count_when(outcome: OperationAttemptOutcome) -> ColumnElement[int]:
    return func.sum(case((OperationAttempt.outcome == outcome, 1), else_=0))
