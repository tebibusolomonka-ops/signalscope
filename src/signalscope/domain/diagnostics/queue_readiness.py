from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.operations.queues import QUEUE_TABLES, QueueTable
from signalscope.domain.sources.scheduling import Clock, utc_now


@dataclass(frozen=True, slots=True)
class QueueObservation:
    """Factual counts for one job queue. No tenant payload is read."""

    queue: str
    query_available: bool
    waiting: int
    running: int
    oldest_waiting_age_seconds: float | None
    expired_leases: int


@dataclass(frozen=True, slots=True)
class QueueReadinessReport:
    queues: tuple[QueueObservation, ...]

    @property
    def all_queryable(self) -> bool:
        return all(queue.query_available for queue in self.queues)


class QueueReadinessService:
    """Observe each job queue with counts only.

    Pending work is normal and never counts as a failure. Only a queue that
    cannot be queried is reported as a dependency failure.
    """

    def __init__(self, session: AsyncSession, *, clock: Clock = utc_now) -> None:
        self.session = session
        self.clock = clock

    async def observe(self) -> QueueReadinessReport:
        now = self.clock()
        observations = [await self._observe(table, now) for table in QUEUE_TABLES.values()]
        return QueueReadinessReport(queues=tuple(observations))

    async def _observe(self, table: QueueTable, now: datetime) -> QueueObservation:
        model = table.model
        pending = table.status("pending")
        running = table.status("running")
        available = (model.status == pending) & (model.available_at <= now)
        try:
            waiting = await self.session.scalar(
                select(func.count()).select_from(model).where(available)
            )
            running_count = await self.session.scalar(
                select(func.count()).select_from(model).where(model.status == running)
            )
            oldest = await self.session.scalar(
                select(func.min(model.available_at)).where(available)
            )
            expired = await self.session.scalar(
                select(func.count())
                .select_from(model)
                .where(
                    model.status == running,
                    model.lease_expires_at.is_not(None),
                    model.lease_expires_at < now,
                )
            )
        except SQLAlchemyError:
            return QueueObservation(table.queue.value, False, 0, 0, None, 0)
        age = None if oldest is None else (now - oldest).total_seconds()
        return QueueObservation(
            queue=table.queue.value,
            query_available=True,
            waiting=waiting or 0,
            running=running_count or 0,
            oldest_waiting_age_seconds=age,
            expired_leases=expired or 0,
        )
