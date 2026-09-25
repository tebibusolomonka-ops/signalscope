import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.domain.ingestion.model import IngestionRun, IngestionStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class IngestionRunFilters:
    source_id: uuid.UUID | None = None
    status: IngestionStatus | None = None


class IngestionRunRepository:
    """Database access for ingestion runs.

    It never commits. The caller decides when the transaction ends.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, run: IngestionRun) -> IngestionRun:
        self.session.add(run)
        # Flush so the database fills in the timestamps and reports errors now.
        await self.session.flush()
        return run

    async def get(self, run_id: uuid.UUID) -> IngestionRun | None:
        return await self.session.get(IngestionRun, run_id)

    async def get_for_update(self, run_id: uuid.UUID) -> IngestionRun | None:
        """Load a run and lock its row until the transaction ends."""
        result = await self.session.scalars(
            select(IngestionRun)
            .where(IngestionRun.id == run_id)
            .with_for_update()
            # Reload a run the session already holds, so callers see the locked row.
            .execution_options(populate_existing=True)
        )
        return result.one_or_none()

    async def add_counts(
        self,
        run_id: uuid.UUID,
        *,
        items_seen: int = 0,
        documents_created: int = 0,
        duplicates_skipped: int = 0,
    ) -> None:
        """Add to a run's counters in the database.

        The addition happens in one UPDATE, so updates at the same time do not
        overwrite each other.
        """
        await self.session.execute(
            update(IngestionRun)
            .where(IngestionRun.id == run_id)
            .values(
                items_seen=IngestionRun.items_seen + items_seen,
                documents_created=IngestionRun.documents_created + documents_created,
                duplicates_skipped=IngestionRun.duplicates_skipped + duplicates_skipped,
            )
        )

    async def list_page(
        self, filters: IngestionRunFilters, limit: int, offset: int
    ) -> list[IngestionRun]:
        result = await self.session.scalars(
            select(IngestionRun)
            .where(*_conditions(filters))
            .order_by(IngestionRun.created_at, IngestionRun.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.all())

    async def count(self, filters: IngestionRunFilters) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(IngestionRun).where(*_conditions(filters))
        )
        return result.scalar_one()


def _conditions(filters: IngestionRunFilters) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if filters.source_id is not None:
        conditions.append(IngestionRun.source_id == filters.source_id)
    if filters.status is not None:
        conditions.append(IngestionRun.status == filters.status)
    return conditions
