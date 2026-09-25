import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, NotFoundError, short_error_message
from signalscope.domain.ingestion.model import IngestionRun, IngestionStatus
from signalscope.domain.ingestion.repository import IngestionRunFilters, IngestionRunRepository
from signalscope.domain.sources.repository import SourceRepository

ALLOWED_CHANGES: dict[IngestionStatus, frozenset[IngestionStatus]] = {
    IngestionStatus.PENDING: frozenset({IngestionStatus.RUNNING}),
    IngestionStatus.RUNNING: frozenset({IngestionStatus.COMPLETED, IngestionStatus.FAILED}),
}


class InvalidStatusChangeError(ConflictError):
    default_message = "Ingestion run cannot change to that status."


class IngestionRunService:
    """Ingestion run operations.

    Writes commit before they return. When a write fails, the session is
    rolled back and the error is raised again.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.runs = IngestionRunRepository(session)
        self.sources = SourceRepository(session)

    async def create(self, source_id: uuid.UUID) -> IngestionRun:
        if await self.sources.get(source_id) is None:
            raise NotFoundError("Source was not found.")
        run = IngestionRun(source_id=source_id, status=IngestionStatus.PENDING)
        try:
            await self.runs.add(run)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return run

    async def get(self, run_id: uuid.UUID) -> IngestionRun:
        run = await self.runs.get(run_id)
        if run is None:
            raise NotFoundError("Ingestion run was not found.")
        return run

    async def list_page(
        self, filters: IngestionRunFilters, limit: int, offset: int
    ) -> tuple[list[IngestionRun], int]:
        """Return one page of matching runs and the total number that match."""
        items = await self.runs.list_page(filters, limit, offset)
        return items, await self.runs.count(filters)

    async def mark_running(self, run_id: uuid.UUID) -> IngestionRun:
        return await self._change_status(run_id, IngestionStatus.RUNNING)

    async def mark_completed(self, run_id: uuid.UUID) -> IngestionRun:
        return await self._change_status(run_id, IngestionStatus.COMPLETED)

    async def mark_failed(self, run_id: uuid.UUID, error_message: str) -> IngestionRun:
        """Mark a run as failed with a short message for people, not a traceback."""
        return await self._change_status(
            run_id, IngestionStatus.FAILED, error_message=short_error_message(error_message)
        )

    async def _change_status(
        self, run_id: uuid.UUID, status: IngestionStatus, error_message: str | None = None
    ) -> IngestionRun:
        try:
            # The row lock stops two workers from changing the same run at once.
            run = await self.runs.get_for_update(run_id)
            if run is None:
                raise NotFoundError("Ingestion run was not found.")
            if status not in ALLOWED_CHANGES.get(run.status, frozenset()):
                raise InvalidStatusChangeError(
                    f"Ingestion run is {run.status} and cannot become {status}."
                )
            now = datetime.now(UTC)
            run.status = status
            if status is IngestionStatus.RUNNING:
                run.started_at = now
            else:
                run.finished_at = now
                run.error_message = error_message
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return run
