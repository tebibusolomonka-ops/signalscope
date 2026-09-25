import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from signalscope.core.errors import ConflictError, NotFoundError
from signalscope.domain.sources.model import MAX_INGESTION_INTERVAL_MINUTES, Source, SourceType
from signalscope.domain.sources.repository import SourceRepository

# Only these types have an adapter that fetches content by itself.
SCHEDULABLE_TYPES = frozenset({SourceType.WEB, SourceType.RSS})

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def check_interval_minutes(interval_minutes: int) -> None:
    if not 1 <= interval_minutes <= MAX_INGESTION_INTERVAL_MINUTES:
        raise ValueError(f"interval_minutes must be between 1 and {MAX_INGESTION_INTERVAL_MINUTES}")


def next_ingestion_time(scheduled_at: datetime, interval_minutes: int, now: datetime) -> datetime:
    """Return the first scheduled time after now.

    Times are counted from the previous scheduled time, not from when the run
    happened, so the schedule does not drift. A source that is late skips the
    times it missed instead of catching up on each one.
    """
    interval = timedelta(minutes=interval_minutes)
    missed = max((now - scheduled_at) // interval, 0)
    return scheduled_at + (missed + 1) * interval


def advance_schedule(source: Source, now: datetime) -> None:
    """Move a source's next ingestion time past now. The caller commits."""
    if source.ingestion_interval_minutes is None or source.next_ingestion_at is None:
        raise ValueError("source has no schedule to advance")
    source.next_ingestion_at = next_ingestion_time(
        source.next_ingestion_at, source.ingestion_interval_minutes, now
    )


class SourceScheduleService:
    """Turns scheduled ingestion on and off for a source.

    Writes commit before they return. When a write fails, the session is
    rolled back and the error is raised again.
    """

    def __init__(self, session: AsyncSession, clock: Clock = utc_now) -> None:
        self.session = session
        self.repository = SourceRepository(session)
        self.clock = clock

    async def enable(
        self, source_id: uuid.UUID, interval_minutes: int, start_at: datetime | None = None
    ) -> Source:
        """Ingest a source every interval_minutes, starting at start_at or now."""
        check_interval_minutes(interval_minutes)
        if start_at is not None and start_at.tzinfo is None:
            raise ValueError("start_at must include a time zone")
        next_at = (start_at or self.clock()).astimezone(UTC)
        try:
            source = await self._get_for_update(source_id)
            if source.type not in SCHEDULABLE_TYPES:
                raise ConflictError(f"{source.type} sources cannot be ingested on a schedule.")
            source.ingestion_enabled = True
            source.ingestion_interval_minutes = interval_minutes
            source.next_ingestion_at = next_at
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return source

    async def disable(self, source_id: uuid.UUID) -> Source:
        """Stop scheduled ingestion.

        The interval is kept, so people can still see what it was.
        """
        try:
            source = await self._get_for_update(source_id)
            source.ingestion_enabled = False
            source.next_ingestion_at = None
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return source

    async def _get_for_update(self, source_id: uuid.UUID) -> Source:
        # The lock keeps the scheduler from moving next_ingestion_at at the same time.
        source = await self.repository.get_for_update(source_id)
        if source is None:
            raise NotFoundError("Source was not found.")
        return source
