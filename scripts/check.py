"""Run the project checks: tests, lint, format, types and migration heads.

Usage: python scripts/check.py

The checks run in order and stop at the first failure. The exit code is the
exit code of the check that failed, or 0 when all of them pass.
"""

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Each tool runs as "python -m <tool>" with this Python, so the tools of the
# active virtual environment are used on Windows and Linux alike.
CHECKS = [
    ("Running pytest", ["pytest"]),
    ("Running Ruff", ["ruff", "check", "."]),
    ("Running format check", ["ruff", "format", "--check", "."]),
    ("Running mypy", ["mypy", "src"]),
]
HEADS_TITLE = "Checking Alembic heads"


def build_commands() -> list[tuple[str, list[str]]]:
    return [(title, [sys.executable, "-m", *arguments]) for title, arguments in CHECKS]


def count_heads(alembic_output: str) -> int:
    return sum(1 for line in alembic_output.splitlines() if line.rstrip().endswith("(head)"))


def check_heads() -> int:
    """Fail unless the migrations have exactly one head."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr, end="", file=sys.stderr)
        return result.returncode
    heads = count_heads(result.stdout)
    if heads != 1:
        print(f"Expected one Alembic head, found {heads}.", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the SignalScope checks.")
    parser.parse_args(argv)

    for title, command in build_commands():
        print(title, flush=True)
        code = subprocess.run(command, cwd=ROOT, check=False).returncode
        if code != 0:
            print(f"Failed: {title.removeprefix('Running ')}", file=sys.stderr)
            return code
    print(HEADS_TITLE, flush=True)
    code = check_heads()
    if code != 0:
        return code
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
