import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.ingestion.job_repository import IngestionJobRepository
from signalscope.domain.ingestion.model import IngestionJob, IngestionRun, IngestionStatus
from signalscope.domain.ingestion.repository import IngestionRunRepository
from signalscope.domain.sources.repository import SourceRepository
from signalscope.domain.sources.scheduling import Clock, advance_schedule, utc_now


@dataclass(frozen=True, slots=True)
class SchedulingResult:
    sources_considered: int
    jobs_created: int


class IngestionScheduler:
    """Queues an ingestion job for every source that is due.

    Each source gets its own short transaction: lock the source, create a
    pending run and a job for it, move next_ingestion_at forward and commit.
    The row lock stops two schedulers from queueing the same source twice.
    """

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], clock: Clock = utc_now
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def schedule_due(self, limit: int) -> SchedulingResult:
        """Queue jobs for at most limit due sources, the longest waiting first."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        now = self.clock()
        async with self.session_factory() as session:
            due = await SourceRepository(session).list_due_for_ingestion(now, limit)
        jobs_created = 0
        for source in due:
            if await self._schedule(source.id, now):
                jobs_created += 1
        return SchedulingResult(sources_considered=len(due), jobs_created=jobs_created)

    async def _schedule(self, source_id: uuid.UUID, now: datetime) -> bool:
        async with self.session_factory() as session:
            try:
                source = await SourceRepository(session).get_due_for_update(source_id, now)
                if source is None:
                    # Another scheduler queued it first, or it was changed meanwhile.
                    return False
                run = await IngestionRunRepository(session).add(
                    IngestionRun(source_id=source.id, status=IngestionStatus.PENDING)
                )
                await IngestionJobRepository(session).add(
                    IngestionJob(source_id=source.id, run_id=run.id, available_at=now)
                )
                advance_schedule(source, now)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return True
