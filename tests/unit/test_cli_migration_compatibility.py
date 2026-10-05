import io
import json

import pytest

from signalscope.cli import build_parser, check_migration_compatibility
from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.migration_compatibility import (
    MigrationCompatibilityReport,
    MigrationCompatibilityState,
)

pytestmark = pytest.mark.anyio


def test_arguments() -> None:
    args = build_parser().parse_args(["check-migration-compatibility", "--json"])
    assert args.json is True


def report(state: MigrationCompatibilityState) -> MigrationCompatibilityReport:
    return MigrationCompatibilityReport(state, ("database",), ("application",), "Detail.")


async def test_current_revision_exits_zero() -> None:
    out = io.StringIO()

    code = await check_migration_compatibility(
        Settings(), out, report=report(MigrationCompatibilityState.CURRENT)
    )

    assert code == 0
    assert "State: current" in out.getvalue()


async def test_mismatch_json_exits_nonzero() -> None:
    out = io.StringIO()

    code = await check_migration_compatibility(
        Settings(),
        out,
        json_output=True,
        report=report(MigrationCompatibilityState.BEHIND),
    )

    assert code == 1
    assert json.loads(out.getvalue())["state"] == "behind"
