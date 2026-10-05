import io
import json
from pathlib import Path

import pytest

from signalscope.cli import build_parser, run_acceptance
from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.acceptance import (
    AcceptanceCheck,
    AcceptanceResult,
    AcceptanceStatus,
)

pytestmark = pytest.mark.anyio


def test_arguments() -> None:
    args = build_parser().parse_args(["run-acceptance", "--profile", "acceptance.json", "--json"])
    assert args.profile == Path("acceptance.json")
    assert args.json is True


async def test_json_output_and_failed_exit() -> None:
    out = io.StringIO()
    result = AcceptanceResult(
        1,
        (AcceptanceCheck("deployment.migration_current", AcceptanceStatus.MISSED, "Missed."),),
        {"build_sha": "abc"},
    )

    code = await run_acceptance(
        Path("unused.json"), Settings(), out, json_output=True, result=result
    )

    assert code == 1
    assert json.loads(out.getvalue())["requirements_missed"] == ["deployment.migration_current"]


async def test_invalid_profile() -> None:
    err = io.StringIO()

    code = await run_acceptance(Path("missing.json"), Settings(), err=err)

    assert code == 1
    assert "Error:" in err.getvalue()
