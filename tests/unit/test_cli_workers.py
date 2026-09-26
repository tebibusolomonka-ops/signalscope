import io
from typing import Any

import pytest

from signalscope import cli
from signalscope.cli import _run_jobs, build_parser, main

pytestmark = pytest.mark.anyio

WORKER_COMMANDS = ["run-worker", "run-processing-worker"]


@pytest.mark.parametrize("command", WORKER_COMMANDS)
def test_default_is_a_long_running_worker(command: str) -> None:
    args = build_parser().parse_args([command])

    assert (args.once, args.poll_seconds, args.max_jobs) == (False, None, None)


@pytest.mark.parametrize("command", WORKER_COMMANDS)
def test_once(command: str) -> None:
    assert build_parser().parse_args([command, "--once"]).once is True


@pytest.mark.parametrize("command", WORKER_COMMANDS)
def test_loop_options(command: str) -> None:
    args = build_parser().parse_args([command, "--poll-seconds", "2.5", "--max-jobs", "10"])

    assert (args.once, args.poll_seconds, args.max_jobs) == (False, 2.5, 10)


@pytest.mark.parametrize("command", WORKER_COMMANDS)
@pytest.mark.parametrize(
    ("options", "message"),
    [
        (["--poll-seconds", "0"], "must be a positive number: 0"),
        (["--poll-seconds", "-1"], "must be a positive number: -1"),
        (["--poll-seconds", "soon"], "must be a number: 'soon'"),
        (["--poll-seconds", "inf"], "must be a positive number: inf"),
        (["--max-jobs", "0"], "must be at least 1: 0"),
        (["--once", "--max-jobs", "2"], "--once cannot be used with"),
        (["--once", "--poll-seconds", "1"], "--once cannot be used with"),
    ],
)
def test_bad_options_are_rejected(
    command: str, options: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([command, *options])

    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("command", "function"),
    [("run-worker", "run_worker"), ("run-processing-worker", "run_processing_worker")],
)
def test_options_reach_the_worker(
    command: str, function: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: dict[str, Any] = {}

    async def fake_worker(settings: object, **options: Any) -> int:
        received.update(options)
        return 0

    monkeypatch.setattr(cli, function, fake_worker)

    assert main([command, "--poll-seconds", "3", "--max-jobs", "7"]) == 0
    assert received == {"once": False, "poll_seconds": 3.0, "max_jobs": 7}


@pytest.mark.parametrize(
    ("command", "function"),
    [("run-worker", "run_worker"), ("run-processing-worker", "run_processing_worker")],
)
def test_ctrl_c_stops_cleanly(
    command: str,
    function: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def interrupted(settings: object, **options: Any) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, function, interrupted)

    assert main([command]) == 0
    assert capsys.readouterr().err == "Stopped.\n"


class Jobs:
    """Plays back job outcomes: True completed, False failed, None no job."""

    def __init__(self, outcomes: list[bool | None]) -> None:
        self.outcomes = outcomes

    async def __call__(self) -> bool | None:
        return self.outcomes.pop(0) if self.outcomes else None


@pytest.mark.parametrize(
    ("outcomes", "code", "output"),
    [
        ([None], 0, "No job.\n"),
        ([True], 0, ""),
        ([False], 1, ""),
    ],
)
async def test_once_mode(outcomes: list[bool | None], code: int, output: str) -> None:
    out = io.StringIO()

    result = await _run_jobs(
        Jobs(outcomes), "No job.", out, once=True, poll_seconds=None, max_jobs=None
    )

    assert (result, out.getvalue()) == (code, output)


async def test_loop_mode_keeps_going_after_a_failed_job() -> None:
    out = io.StringIO()

    result = await _run_jobs(
        Jobs([True, False, True]), "No job.", out, once=False, poll_seconds=0.01, max_jobs=3
    )

    assert result == 0
    assert out.getvalue() == "Jobs handled: 3\n"
