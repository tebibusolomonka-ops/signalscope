import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.operations.attempt import OperationAttempt


@dataclass(frozen=True, slots=True)
class QueueLatencySummary:
    queue: str
    completed: int
    min_seconds: float
    max_seconds: float
    average_seconds: float
    p50_seconds: float
    p95_seconds: float


@dataclass(frozen=True, slots=True)
class OperationLatencyReport:
    organization_id: uuid.UUID
    queues: tuple[QueueLatencySummary, ...]


class OperationLatencyService:
    """Factual duration summaries for completed operation attempts, per queue.

    Only attempts with both a start and a finish time are measured, so running
    attempts are never counted. Percentiles use percentile_disc, which returns an
    actually observed duration, so results are deterministic. All queries are
    bounded by organization, time range and queue.
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
    ) -> OperationLatencyReport:
        duration = cast(
            func.extract("epoch", OperationAttempt.finished_at - OperationAttempt.started_at),
            Float,
        )
        conditions = [
            OperationAttempt.organization_id == organization_id,
            OperationAttempt.started_at.is_not(None),
            OperationAttempt.finished_at.is_not(None),
        ]
        if queue is not None:
            conditions.append(OperationAttempt.queue_name == queue)
        if start is not None:
            conditions.append(OperationAttempt.created_at >= start)
        if end is not None:
            conditions.append(OperationAttempt.created_at < end)

        rows = await self.session.execute(
            select(
                OperationAttempt.queue_name.label("queue"),
                func.count().label("completed"),
                func.min(duration).label("min_seconds"),
                func.max(duration).label("max_seconds"),
                func.avg(duration).label("average_seconds"),
                func.percentile_disc(0.5).within_group(duration.asc()).label("p50_seconds"),
                func.percentile_disc(0.95).within_group(duration.asc()).label("p95_seconds"),
            )
            .where(*conditions)
            .group_by(OperationAttempt.queue_name)
            .order_by(OperationAttempt.queue_name)
        )
        summaries = tuple(
            QueueLatencySummary(
                queue=row.queue.value if hasattr(row.queue, "value") else str(row.queue),
                completed=row.completed,
                min_seconds=float(row.min_seconds),
                max_seconds=float(row.max_seconds),
                average_seconds=float(row.average_seconds),
                p50_seconds=float(row.p50_seconds),
                p95_seconds=float(row.p95_seconds),
            )
            for row in rows
        )
        return OperationLatencyReport(organization_id=organization_id, queues=summaries)
