import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from signalscope.cli import build_parser, create_release_candidate
from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.build_metadata import BuildMetadata
from signalscope.domain.diagnostics.deployment_validation import DeploymentValidationResult
from signalscope.domain.diagnostics.release_candidate import ReleaseCandidateManifest

pytestmark = pytest.mark.anyio


def test_arguments() -> None:
    args = build_parser().parse_args(
        ["create-release-candidate", "--profile", "profile.json", "--output", "rc.json"]
    )
    assert args.profile == Path("profile.json")
    assert args.output == Path("rc.json")


async def test_writes_manifest(tmp_path: Path) -> None:
    output = tmp_path / "candidate.json"
    manifest = ReleaseCandidateManifest(
        datetime(2026, 10, 5, tzinfo=UTC),
        BuildMetadata("0.1.0", "3.12", None, None, None),
        "head",
        DeploymentValidationResult(1, (), None),
        None,
        (),
        {"security_headers_enabled": True},
    )

    code = await create_release_candidate(
        Path("unused.json"), output, Settings(), manifest=manifest
    )

    assert code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["manifest_version"] == 1


async def test_validation_failure_writes_nothing(tmp_path: Path) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text('{"version": 1, "requirements": {"auth_required": true}}', encoding="utf-8")
    output = tmp_path / "candidate.json"
    err = io.StringIO()

    code = await create_release_candidate(profile, output, Settings(), err=err)

    assert code == 1
    assert output.exists() is False
    assert "validation failed" in err.getvalue()
