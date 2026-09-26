from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalscope.domain.ingestion.job_repository import IngestionJobRepository
from signalscope.domain.ingestion.model import IngestionJob, IngestionRun, IngestionStatus
from signalscope.domain.ingestion.repository import IngestionRunRepository

STOPPED_WORKER_ERROR = "Worker stopped before the run finished."


async def recover_stale_ingestion_jobs(
    session_factory: async_sessionmaker[AsyncSession], now: datetime, limit: int
) -> list[IngestionJob]:
    """Put stale ingestion jobs back in the queue and commit.

    A run cannot start twice, so a recovered job whose run already started
    gets a new pending run. A run the lost worker left running is marked
    failed, which keeps it in the history.
    """
    async with session_factory() as session:
        try:
            jobs = await IngestionJobRepository(session).recover_stale(now, limit)
            runs = IngestionRunRepository(session)
            for job in jobs:
                run = await runs.get_for_update(job.run_id)
                if run is None or run.status is IngestionStatus.PENDING:
                    continue
                if run.status is IngestionStatus.RUNNING:
                    run.status = IngestionStatus.FAILED
                    run.finished_at = now
                    run.error_message = STOPPED_WORKER_ERROR
                new_run = await runs.add(
                    IngestionRun(source_id=job.source_id, status=IngestionStatus.PENDING)
                )
                job.run_id = new_run.id
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return jobs
