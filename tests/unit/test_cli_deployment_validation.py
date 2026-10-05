import io
import json
from pathlib import Path

import pytest

from signalscope.cli import build_parser, validate_deployment
from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.deployment_validation import (
    DeploymentRequirementResult,
    DeploymentValidationResult,
    ValidationStatus,
)

pytestmark = pytest.mark.anyio


def test_arguments() -> None:
    args = build_parser().parse_args(["validate-deployment", "profile.json", "--json"])
    assert args.profile == Path("profile.json")
    assert args.json is True


def result(status: ValidationStatus) -> DeploymentValidationResult:
    return DeploymentValidationResult(
        1,
        (DeploymentRequirementResult("migration_current", status, "Detail."),),
        None,
    )


async def test_json_result_and_exit_code() -> None:
    out = io.StringIO()

    code = await validate_deployment(
        Path("unused.json"),
        Settings(),
        out,
        json_output=True,
        result=result(ValidationStatus.MISSED),
    )

    payload = json.loads(out.getvalue())
    assert code == 1
    assert payload["requirements_missed"] == ["migration_current"]


async def test_invalid_profile_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text("not json", encoding="utf-8")
    err = io.StringIO()

    code = await validate_deployment(path, Settings(), err=err)

    assert code == 1
    assert "Error:" in err.getvalue()
