import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import String, cast, func, literal, null, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from signalscope.domain.operations.access import operations_scope
from signalscope.domain.operations.queues import (
    QUEUE_TABLES,
    OperationsQueue,
    QueueTable,
    ResourceType,
)
from signalscope.domain.tenancy.policy import ContentAccessPolicy
from signalscope.domain.tenancy.scope import ContentScope


@dataclass(frozen=True, slots=True)
class FailedJob:
    """A failed job in the shape every queue shares.

    error is the short message stored when the job failed, never a traceback.
    provider and model are only set for chunk jobs, which run one model.
    """

    queue: OperationsQueue
    job_id: uuid.UUID
    status: str
    resource_type: ResourceType
    resource_id: uuid.UUID
    provider: str | None
    model: str | None
    attempt_count: int
    available_at: datetime
    created_at: datetime
    finished_at: datetime | None
    error: str | None


class FailedJobInspectionService:
    """Failed jobs of one organization, newest failure first.

    The organization filter is in each queue's SQL, before the queues are
    combined, ordered and paged.
    """

    def __init__(self, session: AsyncSession, policy: ContentAccessPolicy) -> None:
        self.session = session
        self.policy = policy

    async def list_page(
        self,
        organization_id: uuid.UUID,
        queue: OperationsQueue | None,
        limit: int,
        offset: int,
    ) -> tuple[list[FailedJob], int]:
        scope = await operations_scope(self.policy, organization_id)
        tables = [QUEUE_TABLES[queue]] if queue is not None else list(QUEUE_TABLES.values())
        combined = union_all(*(_failed(table, scope) for table in tables)).subquery()
        rows = (
            await self.session.execute(
                select(combined)
                .order_by(
                    combined.c.finished_at.desc().nulls_last(),
                    combined.c.created_at.desc(),
                    combined.c.job_id,
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()
        total = await self.session.scalar(select(func.count()).select_from(combined))
        return [_job(row) for row in rows], total or 0


def _failed(table: QueueTable, scope: ContentScope) -> Select[tuple[object, ...]]:
    model = table.model
    chunk_job = table.resource_type is ResourceType.CHUNK
    return select(
        literal(table.queue.value, String).label("queue"),
        model.id.label("job_id"),
        cast(model.status, String).label("status"),
        literal(table.resource_type.value, String).label("resource_type"),
        table.resource_id.label("resource_id"),
        (model.provider if chunk_job else cast(null(), String)).label("provider"),
        (model.model if chunk_job else cast(null(), String)).label("model"),
        model.attempt_count.label("attempt_count"),
        model.available_at.label("available_at"),
        model.created_at.label("created_at"),
        model.finished_at.label("finished_at"),
        model.last_error.label("error"),
    ).where(model.status == table.status("failed"), table.in_scope(scope))


def _job(row: object) -> FailedJob:
    values = row._mapping  # type: ignore[attr-defined]
    return FailedJob(
        queue=OperationsQueue(values["queue"]),
        job_id=values["job_id"],
        status=values["status"],
        resource_type=ResourceType(values["resource_type"]),
        resource_id=values["resource_id"],
        provider=values["provider"],
        model=values["model"],
        attempt_count=values["attempt_count"],
        available_at=values["available_at"],
        created_at=values["created_at"],
        finished_at=values["finished_at"],
        error=values["error"],
    )
