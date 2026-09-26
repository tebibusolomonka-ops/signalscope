import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from signalscope.core.errors import SignalScopeError
from signalscope.core.leases import DEFAULT_LEASE_POLICY, LeasePolicy

logger = logging.getLogger(__name__)

# A worker sends this many heartbeats per lease, so one missed heartbeat does
# not make the job look abandoned.
HEARTBEATS_PER_LEASE = 3

Heartbeat = Callable[[], Awaitable[bool]]
Sleep = Callable[[float], Awaitable[None]]


class JobLeaseLostError(SignalScopeError):
    default_message = "Job lease was lost while the work was running."


def heartbeat_seconds(lease: LeasePolicy) -> float:
    return lease.duration.total_seconds() / HEARTBEATS_PER_LEASE


class LeaseKeeper:
    """Extends the lease of a claimed job while the work runs.

    lost becomes True when a heartbeat reports that the job is no longer held,
    which means another worker recovered it. A heartbeat that raises is logged
    and tried again, because the lease may still be valid.
    """

    def __init__(self, heartbeat: Heartbeat, seconds: float, sleep: Sleep) -> None:
        self.heartbeat = heartbeat
        self.seconds = seconds
        self.sleep = sleep
        self.lost = False
        self.beats = 0

    async def run(self) -> None:
        while True:
            await self.sleep(self.seconds)
            try:
                held = await self.heartbeat()
            except Exception:
                logger.exception("Could not extend a job lease")
                continue
            if not held:
                self.lost = True
                return
            self.beats += 1

    def check(self) -> None:
        if self.lost:
            raise JobLeaseLostError()


@asynccontextmanager
async def keep_lease_alive(
    heartbeat: Heartbeat,
    lease: LeasePolicy = DEFAULT_LEASE_POLICY,
    sleep: Sleep = asyncio.sleep,
) -> AsyncIterator[LeaseKeeper]:
    """Extend a job lease in the background until the block ends."""
    keeper = LeaseKeeper(heartbeat, heartbeat_seconds(lease), sleep)
    task = asyncio.create_task(keeper.run())
    try:
        yield keeper
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
