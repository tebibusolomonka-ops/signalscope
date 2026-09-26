from datetime import UTC, datetime, timedelta

import pytest

from signalscope.core.leases import DEFAULT_LEASE_POLICY, LeasePolicy

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def test_default_lease_is_five_minutes() -> None:
    assert DEFAULT_LEASE_POLICY.expires_at(NOW) == NOW + timedelta(minutes=5)


def test_custom_lease() -> None:
    assert LeasePolicy(timedelta(seconds=30)).expires_at(NOW) == NOW + timedelta(seconds=30)


@pytest.mark.parametrize("duration", [timedelta(0), timedelta(seconds=-1)])
def test_lease_must_be_positive(duration: timedelta) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        LeasePolicy(duration)
