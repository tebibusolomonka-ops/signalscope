import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_script", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = load_script()


def test_commands_use_the_current_python() -> None:
    commands = check.build_commands()

    assert [title for title, _ in commands] == [
        "Running pytest",
        "Running Ruff",
        "Running format check",
        "Running mypy",
    ]
    assert [command for _, command in commands] == [
        [sys.executable, "-m", "pytest"],
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        [sys.executable, "-m", "mypy", "src"],
    ]


@pytest.mark.parametrize(
    ("output", "heads"),
    [
        ("dc4e91a00110 (head)\n", 1),
        ("aaa (head)\nbbb (head)\n", 2),
        ("", 0),
    ],
)
def test_count_heads(output: str, heads: int) -> None:
    assert check.count_heads(output) == heads


class FakeRun:
    """Stands in for subprocess.run and returns the given exit codes in order."""

    def __init__(self, codes: list[int], heads_output: str = "abc (head)\n") -> None:
        self.codes = codes
        self.heads_output = heads_output
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if command[-2:] == ["alembic", "heads"]:
            return subprocess.CompletedProcess(command, 0, self.heads_output, "")
        return subprocess.CompletedProcess(command, self.codes.pop(0), "", "")


def test_all_checks_pass(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeRun([0, 0, 0, 0])
    monkeypatch.setattr(check.subprocess, "run", fake)

    assert check.main([]) == 0
    assert len(fake.commands) == 5
    assert capsys.readouterr().out.splitlines() == [
        "Running pytest",
        "Running Ruff",
        "Running format check",
        "Running mypy",
        "Checking Alembic heads",
        "abc (head)",
        "All checks passed.",
    ]


def test_stops_at_the_first_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeRun([0, 3, 0, 0])
    monkeypatch.setattr(check.subprocess, "run", fake)

    assert check.main([]) == 3
    assert len(fake.commands) == 2
    assert capsys.readouterr().err == "Failed: Ruff\n"


def test_two_heads_fail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check.subprocess, "run", FakeRun([0, 0, 0, 0], "a (head)\nb (head)\n"))

    assert check.main([]) == 1
    assert "Expected one Alembic head, found 2." in capsys.readouterr().err


def test_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        check.main(["--help"])

    assert exit_info.value.code == 0
    assert "Run the SignalScope checks." in capsys.readouterr().out
