from datetime import timedelta

import pytest

from signalscope.domain.blobs.cleanup import retry_delay


@pytest.mark.parametrize(
    ("attempts", "minutes"),
    [(0, 1), (1, 1), (2, 2), (3, 4), (4, 8), (10, 512)],
)
def test_delay_doubles(attempts: int, minutes: int) -> None:
    assert retry_delay(attempts) == timedelta(minutes=minutes)


@pytest.mark.parametrize("attempts", [12, 50, 10_000])
def test_delay_stops_at_one_day(attempts: int) -> None:
    assert retry_delay(attempts) == timedelta(days=1)
