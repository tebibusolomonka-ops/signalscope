import asyncio
import contextlib
from collections.abc import Awaitable, Callable

Work = Callable[[], Awaitable[bool]]
Sleep = Callable[[float], Awaitable[None]]

DEFAULT_POLL_SECONDS = 5.0


class WorkerLoop:
    """Calls a worker again and again until it is stopped.

    work() handles at most one job and returns whether there was one. After a
    job the loop asks for the next one right away. When there was no work, it
    waits poll_seconds first.

    The loop ends when stop() is called, or after max_jobs jobs. A job that is
    running when stop() is called is finished first.

    Workers turn failed jobs into failed job rows themselves, so a failed job
    does not end the loop. An exception from work() means something else is
    wrong, such as the database being down. It ends the loop and is raised
    again, so the process can exit and be restarted.
    """

    def __init__(
        self,
        work: Work,
        *,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        max_jobs: int | None = None,
        sleep: Sleep | None = None,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be at least 1")
        self.work = work
        self.poll_seconds = poll_seconds
        self.max_jobs = max_jobs
        # Tests pass their own sleep. Otherwise the pause ends early on stop().
        self.sleep = sleep
        self.stop_requested = asyncio.Event()

    def stop(self) -> None:
        self.stop_requested.set()

    async def run(self) -> int:
        """Run until stopped and return how many jobs were handled."""
        jobs = 0
        while not self.stop_requested.is_set():
            if self.max_jobs is not None and jobs >= self.max_jobs:
                break
            if await self.work():
                jobs += 1
            else:
                await self._pause()
        return jobs

    async def _pause(self) -> None:
        if self.sleep is not None:
            await self.sleep(self.poll_seconds)
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.stop_requested.wait(), timeout=self.poll_seconds)
