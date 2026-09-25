from datetime import UTC, datetime, timedelta

import pytest

from signalscope.domain.sources.model import MAX_INGESTION_INTERVAL_MINUTES, Source, SourceType
from signalscope.domain.sources.scheduling import (
    advance_schedule,
    check_interval_minutes,
    next_ingestion_time,
)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 5, 1, hour, minute, tzinfo=UTC)


def scheduled_source(next_ingestion_at: datetime | None, interval: int | None = 60) -> Source:
    return Source(
        type=SourceType.RSS,
        name="Example feed",
        url="https://example.com/rss",
        ingestion_enabled=True,
        ingestion_interval_minutes=interval,
        next_ingestion_at=next_ingestion_at,
    )


def test_next_time_counts_from_the_scheduled_time() -> None:
    # A run due at 10:00 that starts at 10:07 is next due at 11:00, not 11:07.
    assert next_ingestion_time(at(10), 60, now=at(10, 7)) == at(11)


def test_late_source_skips_missed_times() -> None:
    assert next_ingestion_time(at(10), 60, now=at(13, 30)) == at(14)


def test_next_time_is_after_now() -> None:
    assert next_ingestion_time(at(10), 60, now=at(11)) == at(12)


def test_next_time_before_the_scheduled_time() -> None:
    assert next_ingestion_time(at(10), 15, now=at(9, 50)) == at(10, 15)


def test_schedule_does_not_drift() -> None:
    source = scheduled_source(at(10))

    for now in [at(10, 7), at(11, 12), at(12, 3)]:
        advance_schedule(source, now)

    assert source.next_ingestion_at == at(13)


def test_short_intervals() -> None:
    source = scheduled_source(at(10), interval=5)

    advance_schedule(source, at(10, 12))

    assert source.next_ingestion_at == at(10, 15)


def test_next_time_keeps_its_time_zone() -> None:
    next_time = next_ingestion_time(at(10), 60, now=at(10, 1))

    assert next_time.tzinfo is UTC


def test_source_without_a_schedule_cannot_be_advanced() -> None:
    with pytest.raises(ValueError, match="no schedule"):
        advance_schedule(scheduled_source(None), at(10))
    with pytest.raises(ValueError, match="no schedule"):
        advance_schedule(scheduled_source(at(10), interval=None), at(10))


@pytest.mark.parametrize("interval", [1, 60, MAX_INGESTION_INTERVAL_MINUTES])
def test_valid_intervals(interval: int) -> None:
    check_interval_minutes(interval)


@pytest.mark.parametrize("interval", [0, -1, MAX_INGESTION_INTERVAL_MINUTES + 1])
def test_invalid_intervals(interval: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 10080"):
        check_interval_minutes(interval)


def test_one_week_is_the_longest_interval() -> None:
    assert timedelta(minutes=MAX_INGESTION_INTERVAL_MINUTES) == timedelta(weeks=1)
