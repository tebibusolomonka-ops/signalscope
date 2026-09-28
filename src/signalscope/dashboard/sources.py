import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import NotFoundError
from signalscope.dashboard.series import day_range, end_of, fill, start_of, utc_day
from signalscope.domain.documents.model import Document
from signalscope.domain.sources.model import Source
from signalscope.domain.sources.scheduling import Clock, utc_now


@dataclass(frozen=True, slots=True)
class SourceActivityDay:
    # A UTC calendar date.
    date: date
    # Documents SignalScope stored that day.
    documents_created: int
    # Documents whose publication date is that day. Documents without one are not counted.
    documents_published: int


class SourceActivityService:
    """Daily document counts for the last days, for all sources or one. Facts only."""

    def __init__(self, session: AsyncSession, clock: Clock = utc_now) -> None:
        self.session = session
        self.clock = clock

    async def daily(self, days: int, source_id: uuid.UUID | None = None) -> list[SourceActivityDay]:
        """One entry per UTC day, oldest first, ending today, with 0 for quiet days."""
        dates = day_range(days, self.clock())
        if source_id is not None and await self.session.get(Source, source_id) is None:
            raise NotFoundError("Source was not found.")
        created = await self._counts(Document.created_at, dates, source_id)
        published = await self._counts(Document.published_at, dates, source_id)
        return [SourceActivityDay(day, created[day], published[day]) for day in dates]

    async def _counts(
        self, column: Any, dates: list[date], source_id: uuid.UUID | None
    ) -> dict[date, int]:
        day = utc_day(column)
        statement = (
            select(day, func.count())
            .where(column >= start_of(dates[0]), column < end_of(dates[-1]))
            .group_by(day)
        )
        if source_id is not None:
            statement = statement.where(Document.source_id == source_id)
        rows = await self.session.execute(statement)
        return fill(dates, ((found, count) for found, count in rows))
