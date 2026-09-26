from dataclasses import dataclass
from datetime import datetime, timedelta

DEFAULT_LEASE_DURATION = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class LeasePolicy:
    """How long a worker may hold a claimed job without a heartbeat.

    When the lease runs out, the worker is taken to be gone, and the job can
    be put back in the queue.
    """

    duration: timedelta = DEFAULT_LEASE_DURATION

    def __post_init__(self) -> None:
        if self.duration <= timedelta(0):
            raise ValueError("lease duration must be positive")

    def expires_at(self, now: datetime) -> datetime:
        return now + self.duration


DEFAULT_LEASE_POLICY = LeasePolicy()
