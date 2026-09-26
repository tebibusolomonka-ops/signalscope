import asyncio

import pytest

from signalscope.workers.runner import WorkerLoop

pytestmark = pytest.mark.anyio

# Every test that could loop forever runs under this limit instead of hanging.
TIMEOUT_SECONDS = 5


class ScriptedWork:
    """Answers with the given results, then reports no work."""

    def __init__(self, results: list[bool]) -> None:
        self.results = results
        self.calls = 0

    async def __call__(self) -> bool:
        self.calls += 1
        return self.results.pop(0) if self.results else False


class RecordingSleep:
    """Records each pause and stops the loop after a number of them."""

    def __init__(self, stop_after: int) -> None:
        self.stop_after = stop_after
        self.pauses: list[float] = []
        self.loop: WorkerLoop | None = None

    async def __call__(self, seconds: float) -> None:
        self.pauses.append(seconds)
        if len(self.pauses) >= self.stop_after and self.loop is not None:
            self.loop.stop()


async def run(loop: WorkerLoop) -> int:
    return await asyncio.wait_for(loop.run(), timeout=TIMEOUT_SECONDS)


async def test_jobs_run_back_to_back() -> None:
    work = ScriptedWork([True, True, True])
    sleep = RecordingSleep(stop_after=1)
    loop = WorkerLoop(work, poll_seconds=2, sleep=sleep)
    sleep.loop = loop

    assert await run(loop) == 3
    # No pause between jobs, one pause once the queue was empty.
    assert sleep.pauses == [2]


async def test_no_work_waits_between_polls() -> None:
    work = ScriptedWork([])
    sleep = RecordingSleep(stop_after=3)
    loop = WorkerLoop(work, poll_seconds=7.5, sleep=sleep)
    sleep.loop = loop

    assert await run(loop) == 0
    assert sleep.pauses == [7.5, 7.5, 7.5]
    assert work.calls == 3


async def test_new_work_after_waiting_is_handled() -> None:
    work = ScriptedWork([True, False, True])
    sleep = RecordingSleep(stop_after=2)
    loop = WorkerLoop(work, poll_seconds=1, sleep=sleep)
    sleep.loop = loop

    assert await run(loop) == 2


async def test_max_jobs() -> None:
    work = ScriptedWork([True] * 10)
    loop = WorkerLoop(work, max_jobs=4, sleep=RecordingSleep(stop_after=100))

    assert await run(loop) == 4
    assert work.calls == 4


async def test_max_jobs_still_waits_for_work() -> None:
    work = ScriptedWork([False, True, False, True])
    sleep = RecordingSleep(stop_after=100)
    loop = WorkerLoop(work, poll_seconds=3, max_jobs=2, sleep=sleep)

    assert await run(loop) == 2
    assert sleep.pauses == [3, 3]


async def test_stopped_loop_does_no_work() -> None:
    work = ScriptedWork([True])
    loop = WorkerLoop(work)
    loop.stop()

    assert await run(loop) == 0
    assert work.calls == 0


async def test_stop_lets_the_current_job_finish() -> None:
    loop: WorkerLoop

    async def work() -> bool:
        loop.stop()
        return True

    loop = WorkerLoop(work, sleep=RecordingSleep(stop_after=100))

    assert await run(loop) == 1


async def test_stop_ends_a_pause_early() -> None:
    work = ScriptedWork([])
    # A long poll, so only stop() can end the pause in time.
    loop = WorkerLoop(work, poll_seconds=3600)

    task = asyncio.create_task(loop.run())
    await asyncio.sleep(0.05)
    loop.stop()

    assert await asyncio.wait_for(task, timeout=TIMEOUT_SECONDS) == 0
    assert work.calls == 1


async def test_worker_error_ends_the_loop() -> None:
    calls = 0

    async def work() -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ConnectionError("database is down")
        return True

    loop = WorkerLoop(work, sleep=RecordingSleep(stop_after=100))

    with pytest.raises(ConnectionError, match="database is down"):
        await run(loop)
    assert calls == 2


@pytest.mark.parametrize("poll_seconds", [0, -1])
def test_poll_seconds_must_be_positive(poll_seconds: float) -> None:
    with pytest.raises(ValueError, match="poll_seconds must be positive"):
        WorkerLoop(ScriptedWork([]), poll_seconds=poll_seconds)


def test_max_jobs_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_jobs must be at least 1"):
        WorkerLoop(ScriptedWork([]), max_jobs=0)
