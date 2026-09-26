import asyncio
import contextlib
import logging
import signal
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from types import FrameType

logger = logging.getLogger(__name__)

Stop = Callable[[], None]
Undo = Callable[[], None]

# SIGINT is Ctrl+C. SIGTERM is what service managers send. Windows knows both
# names, but only really delivers SIGINT.
STOP_SIGNALS: tuple[signal.Signals, ...] = tuple(
    getattr(signal, name) for name in ("SIGINT", "SIGTERM") if hasattr(signal, name)
)


@contextmanager
def stop_on_signals(
    stop: Stop, signals: Sequence[signal.Signals] = STOP_SIGNALS
) -> Iterator[list[signal.Signals]]:
    """Call stop() when the process is asked to stop, and put the handlers back after.

    Yields the signals that are being watched. The list is empty when the
    platform or the current thread allows no handlers at all. The caller then
    still gets KeyboardInterrupt for Ctrl+C.
    """
    loop = asyncio.get_running_loop()
    watched: list[signal.Signals] = []
    undo: list[Undo] = []
    for number in signals:
        remove = _watch(loop, number, stop)
        if remove is not None:
            watched.append(number)
            undo.append(remove)
    try:
        yield watched
    finally:
        for remove in undo:
            remove()


def _watch(loop: asyncio.AbstractEventLoop, number: signal.Signals, stop: Stop) -> Undo | None:
    try:
        loop.add_signal_handler(number, stop)
    except NotImplementedError:
        # Windows event loops have no signal handlers.
        return _watch_with_signal_module(loop, number, stop)
    except (RuntimeError, ValueError):
        logger.debug("Could not watch %s", number.name)
        return None
    return lambda: _unwatch(loop, number)


def _unwatch(loop: asyncio.AbstractEventLoop, number: signal.Signals) -> None:
    with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
        loop.remove_signal_handler(number)


def _watch_with_signal_module(
    loop: asyncio.AbstractEventLoop, number: signal.Signals, stop: Stop
) -> Undo | None:
    def handle(signum: int, frame: FrameType | None) -> None:
        # The handler runs outside the loop, so hand the work back to it.
        loop.call_soon_threadsafe(stop)

    try:
        previous = signal.signal(number, handle)
    except (OSError, ValueError):
        # Not the main thread, or this signal cannot be watched here.
        logger.debug("Could not watch %s", number.name)
        return None
    return lambda: _restore(number, previous)


def _restore(number: signal.Signals, previous: object) -> None:
    with contextlib.suppress(OSError, ValueError, TypeError):
        signal.signal(number, previous)  # type: ignore[arg-type]
