import asyncio
from datetime import timedelta

import pytest

from signalscope.core.leases import DEFAULT_LEASE_POLICY, LeasePolicy
from signalscope.workers.heartbeat import (
    JobLeaseLostError,
    LeaseKeeper,
    heartbeat_seconds,
    keep_lease_alive,
)

pytestmark = pytest.mark.anyio

# Short enough to be quick, long enough that a beat cannot be missed by accident.
FAST_LEASE = LeasePolicy(timedelta(milliseconds=30))
# Every wait is guarded, so a broken keeper fails instead of hanging.
TIMEOUT_SECONDS = 5


class RecordingHeartbeat:
    """Answers with the given results, then keeps saying the job is held."""

    def __init__(self, results: list[bool] | None = None, error: Exception | None = None) -> None:
        self.results = results or []
        self.error = error
        self.calls = 0
        self.called = asyncio.Event()

    async def __call__(self) -> bool:
        self.calls += 1
        self.called.set()
        if self.error is not None and self.calls == 1:
            raise self.error
        return self.results.pop(0) if self.results else True

    async def wait_for(self, calls: int) -> None:
        while self.calls < calls:
            self.called.clear()
            await asyncio.wait_for(self.called.wait(), TIMEOUT_SECONDS)


async def rest() -> None:
    """Wait long enough that a running keeper would beat again."""
    await asyncio.sleep(heartbeat_seconds(FAST_LEASE) * 3)


def test_default_lease_beats_three_times() -> None:
    assert heartbeat_seconds(DEFAULT_LEASE_POLICY) == 100
    assert heartbeat_seconds(LeasePolicy(timedelta(seconds=30))) == 10


async def test_lease_is_extended_while_work_runs() -> None:
    heartbeat = RecordingHeartbeat()

    async with keep_lease_alive(heartbeat, FAST_LEASE) as keeper:
        await heartbeat.wait_for(2)

    assert keeper.beats >= 2
    assert not keeper.lost


async def test_short_work_needs_no_heartbeat() -> None:
    heartbeat = RecordingHeartbeat()

    async with keep_lease_alive(heartbeat, FAST_LEASE) as keeper:
        pass

    assert (heartbeat.calls, keeper.lost) == (0, False)


async def test_heartbeat_stops_after_the_work() -> None:
    heartbeat = RecordingHeartbeat()

    async with keep_lease_alive(heartbeat, FAST_LEASE):
        await heartbeat.wait_for(1)
    calls = heartbeat.calls

    await rest()

    assert heartbeat.calls == calls


async def test_heartbeat_stops_after_a_failure() -> None:
    heartbeat = RecordingHeartbeat()

    with pytest.raises(RuntimeError, match="parsing failed"):
        async with keep_lease_alive(heartbeat, FAST_LEASE):
            await heartbeat.wait_for(1)
            raise RuntimeError("parsing failed")
    calls = heartbeat.calls

    await rest()

    assert heartbeat.calls == calls


async def test_lost_lease_is_reported() -> None:
    heartbeat = RecordingHeartbeat([True, False])

    async with keep_lease_alive(heartbeat, FAST_LEASE) as keeper:
        await heartbeat.wait_for(2)
        # The keeper stops after losing the job, so the work can finish quietly.
        await rest()

    assert keeper.lost
    assert heartbeat.calls == 2
    with pytest.raises(JobLeaseLostError, match="Job lease was lost"):
        keeper.check()


async def test_a_held_lease_passes_the_check() -> None:
    async with keep_lease_alive(RecordingHeartbeat(), FAST_LEASE) as keeper:
        keeper.check()


async def test_failing_heartbeat_is_tried_again(caplog: pytest.LogCaptureFixture) -> None:
    heartbeat = RecordingHeartbeat(error=ConnectionError("database is down"))

    async with keep_lease_alive(heartbeat, FAST_LEASE) as keeper:
        await heartbeat.wait_for(2)

    assert not keeper.lost
    assert keeper.beats >= 1
    assert "Could not extend a job lease" in caplog.text


async def test_keeper_waits_before_the_first_beat() -> None:
    heartbeat = RecordingHeartbeat()
    keeper = LeaseKeeper(heartbeat, seconds=60, sleep=asyncio.sleep)

    task = asyncio.create_task(keeper.run())
    await asyncio.sleep(0)
    task.cancel()

    assert heartbeat.calls == 0
