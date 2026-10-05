import io
import json

import pytest

from signalscope.cli import build_parser, startup_preflight
from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.build_metadata import BuildMetadata
from signalscope.domain.diagnostics.migration_compatibility import (
    MigrationCompatibilityReport,
    MigrationCompatibilityState,
)
from signalscope.domain.diagnostics.production_config import Level
from signalscope.domain.diagnostics.startup_preflight import (
    PreflightCheck,
    StartupPreflightReport,
)

pytestmark = pytest.mark.anyio


def test_arguments() -> None:
    args = build_parser().parse_args(["startup-preflight", "--json"])
    assert args.json is True


def report(level: Level) -> StartupPreflightReport:
    return StartupPreflightReport(
        checks=(PreflightCheck("database", level, "Database check."),),
        build=BuildMetadata("0.1.0", "3.12.10", "abc123", None, None),
        migration=MigrationCompatibilityReport(
            MigrationCompatibilityState.CURRENT, ("head",), ("head",), "Current."
        ),
    )


async def test_text_output_and_exit_status() -> None:
    out = io.StringIO()

    code = await startup_preflight(Settings(), out, report=report(Level.ERROR))

    assert code == 1
    assert out.getvalue() == "ERROR: database: Database check.\n"


async def test_json_output() -> None:
    out = io.StringIO()

    code = await startup_preflight(Settings(), out, json_output=True, report=report(Level.PASS))

    payload = json.loads(out.getvalue())
    assert code == 0
    assert payload["passed"] is True
    assert payload["build"]["build_sha"] == "abc123"
