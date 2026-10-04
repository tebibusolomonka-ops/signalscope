import io
import json

import pytest

from signalscope.cli import build_parser, deployment_diagnostics
from signalscope.core.settings import Settings

pytestmark = pytest.mark.anyio


def test_arguments() -> None:
    args = build_parser().parse_args(["deployment-diagnostics", "--json"])
    assert args.json is True


async def test_without_database_reports_unhealthy() -> None:
    out = io.StringIO()

    code = await deployment_diagnostics(Settings(), out)

    assert code == 1
    assert "Healthy: no" in out.getvalue()


async def test_json_output_is_valid_and_has_no_secret() -> None:
    out = io.StringIO()

    await deployment_diagnostics(Settings(), out, json_output=True)

    payload = json.loads(out.getvalue())
    assert payload["healthy"] is False
    assert payload["readiness"] is None
