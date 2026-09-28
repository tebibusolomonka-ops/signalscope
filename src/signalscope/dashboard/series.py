"""Shared helpers for daily series: UTC day ranges and zero filling."""

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Date, cast, func, literal_column

from signalscope.core.errors import InvalidInputError

MIN_DAYS = 1
MAX_DAYS = 365


def day_range(days: int, now: datetime) -> list[date]:
    """The last days UTC dates, oldest first, ending with today."""
    if not MIN_DAYS <= days <= MAX_DAYS:
        raise InvalidInputError(f"days must be from {MIN_DAYS} to {MAX_DAYS}.")
    today = now.astimezone(UTC).date()
    return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def start_of(day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=UTC)


def end_of(day: date) -> datetime:
    """The start of the next UTC day."""
    return start_of(day) + timedelta(days=1)


def utc_day(column: Any) -> Any:
    """The UTC calendar date of a timestamp column, in SQL.

    'UTC' is written into the SQL, not bound, so the same expression can be
    used in SELECT and GROUP BY.
    """
    return cast(func.timezone(literal_column("'UTC'"), column), Date)


def fill(days: list[date], counts: Iterable[tuple[date, int]]) -> dict[date, int]:
    """Counts for every day, with 0 for days that had none."""
    found = dict(counts)
    return {day: found.get(day, 0) for day in days}
