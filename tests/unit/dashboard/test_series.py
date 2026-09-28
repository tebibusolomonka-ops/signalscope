from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from signalscope.core.errors import InvalidInputError
from signalscope.dashboard.series import day_range, end_of, fill, start_of


def test_day_range_ends_today_in_utc() -> None:
    # 01:00 on 5 March in UTC+3 is still 4 March in UTC.
    now = datetime(2026, 3, 5, 1, 0, tzinfo=timezone(timedelta(hours=3)))

    assert day_range(3, now) == [date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)]
    assert day_range(1, now) == [date(2026, 3, 4)]
    assert len(day_range(365, now)) == 365


@pytest.mark.parametrize("days", [0, -1, 366])
def test_day_range_bounds(days: int) -> None:
    with pytest.raises(InvalidInputError, match="from 1 to 365"):
        day_range(days, datetime(2026, 3, 4, tzinfo=UTC))


def test_fill_gives_every_day() -> None:
    days = [date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)]

    assert fill(days, [(date(2026, 3, 3), 5)]) == {days[0]: 0, days[1]: 5, days[2]: 0}


def test_day_bounds() -> None:
    assert start_of(date(2026, 3, 4)) == datetime(2026, 3, 4, tzinfo=UTC)
    assert end_of(date(2026, 3, 4)) == datetime(2026, 3, 5, tzinfo=UTC)
