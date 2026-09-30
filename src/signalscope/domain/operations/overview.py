import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import NotFoundError
from signalscope.domain.operations.access import operations_scope
from signalscope.domain.operations.queues import QUEUE_TABLES, OperationsQueue, QueueTable
from signalscope.domain.organizations.model import Organization
from signalscope.domain.tenancy.policy import ContentAccessPolicy
from signalscope.domain.tenancy.scope import ContentScope


@dataclass(frozen=True, slots=True)
class QueueSummary:
    """Stored job states of one queue for one organization.

    Running jobs are counted as stored, also when their lease has run out
    and a worker will put them back in the queue.
    """

    queue: OperationsQueue
    pending_count: int
    running_count: int
    failed_count: int
    # When the longest waiting pending job became available.
    oldest_pending_at: datetime | None
    # When the earliest failed job that is still failed finished.
    oldest_failed_at: datetime | None


@dataclass(frozen=True, slots=True)
class OperationsOverview:
    organization: Organization
    queues: list[QueueSummary]


class OrganizationOperationsService:
    """Job counts per queue for one organization's owners, admins and system admins.

    Every count is filtered in SQL through the job's source, document or
    chunk; there is no view of all organizations together.
    """

    def __init__(self, session: AsyncSession, policy: ContentAccessPolicy) -> None:
        self.session = session
        self.policy = policy

    async def overview(self, organization_id: uuid.UUID) -> OperationsOverview:
        scope = await operations_scope(self.policy, organization_id)
        organization = await self.session.get(Organization, organization_id)
        if organization is None:
            raise NotFoundError("Organization was not found.")
        queues = [await self._summary(table, scope) for table in QUEUE_TABLES.values()]
        return OperationsOverview(organization=organization, queues=queues)

    async def _summary(self, table: QueueTable, scope: ContentScope) -> QueueSummary:
        model = table.model
        pending = model.status == table.status("pending")
        running = model.status == table.status("running")
        failed = model.status == table.status("failed")
        row = (
            await self.session.execute(
                select(
                    func.count().filter(pending),
                    func.count().filter(running),
                    func.count().filter(failed),
                    func.min(model.available_at).filter(pending),
                    func.min(model.finished_at).filter(failed),
                ).where(table.in_scope(scope))
            )
        ).one()
        return QueueSummary(
            queue=table.queue,
            pending_count=row[0],
            running_count=row[1],
            failed_count=row[2],
            oldest_pending_at=row[3],
            oldest_failed_at=row[4],
        )
