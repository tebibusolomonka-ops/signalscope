import asyncio
import io
import signal

import pytest

from signalscope.cli import STOPPING_MESSAGE, _run_jobs
from signalscope.workers.runner import WorkerLoop
from signalscope.workers.shutdown import STOP_SIGNALS, stop_on_signals

pytestmark = pytest.mark.anyio

# Every wait is guarded, so a missed signal fails instead of hanging.
TIMEOUT_SECONDS = 5


async def raise_and_wait(number: signal.Signals, stopped: asyncio.Event) -> None:
    signal.raise_signal(number)
    await asyncio.wait_for(stopped.wait(), TIMEOUT_SECONDS)


def test_both_stop_signals_are_known() -> None:
    assert signal.SIGINT in STOP_SIGNALS
    assert signal.SIGTERM in STOP_SIGNALS


@pytest.mark.parametrize("number", [signal.SIGINT, signal.SIGTERM])
async def test_signal_asks_the_worker_to_stop(number: signal.Signals) -> None:
    stopped = asyncio.Event()

    with stop_on_signals(stopped.set) as watched:
        if number not in watched:
            pytest.skip(f"{number.name} cannot be watched here")
        await raise_and_wait(number, stopped)

    assert stopped.is_set()


async def test_nothing_is_watched_without_signals() -> None:
    with stop_on_signals(lambda: None, signals=()) as watched:
        assert watched == []


async def test_windows_style_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        type(loop),
        "add_signal_handler",
        lambda *args: (_ for _ in ()).throw(NotImplementedError()),
    )
    stopped = asyncio.Event()

    with stop_on_signals(stopped.set, signals=(signal.SIGINT,)) as watched:
        assert watched == [signal.SIGINT]
        await raise_and_wait(signal.SIGINT, stopped)


async def test_no_handlers_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        type(loop),
        "add_signal_handler",
        lambda *args: (_ for _ in ()).throw(NotImplementedError()),
    )
    monkeypatch.setattr(
        signal, "signal", lambda *args: (_ for _ in ()).throw(ValueError("not the main thread"))
    )

    with stop_on_signals(lambda: None) as watched:
        assert watched == []


async def test_loop_finishes_the_current_job_then_stops() -> None:
    calls = 0
    loop = WorkerLoop(lambda: work(), poll_seconds=0.01)

    async def work() -> bool:
        nonlocal calls
        calls += 1
        signal.raise_signal(signal.SIGINT)
        await asyncio.wait_for(loop.stop_requested.wait(), TIMEOUT_SECONDS)
        return True

    with stop_on_signals(loop.stop) as watched:
        if signal.SIGINT not in watched:
            pytest.skip("SIGINT cannot be watched here")
        jobs = await asyncio.wait_for(loop.run(), TIMEOUT_SECONDS)

    assert (calls, jobs) == (1, 1)


async def test_worker_command_stops_on_a_signal() -> None:
    out = io.StringIO()
    calls = 0

    async def work() -> bool | None:
        nonlocal calls
        calls += 1
        signal.raise_signal(signal.SIGINT)
        # Give the loop a moment to see the signal before this job ends.
        for _ in range(100):
            await asyncio.sleep(0)
            if STOPPING_MESSAGE in out.getvalue():
                break
        return True

    code = await asyncio.wait_for(
        _run_jobs(work, "No job.", out, once=False, poll_seconds=0.01, max_jobs=5),
        TIMEOUT_SECONDS,
    )

    assert code == 0
    assert calls == 1
    assert out.getvalue().splitlines() == [STOPPING_MESSAGE, "Jobs handled: 1"]
