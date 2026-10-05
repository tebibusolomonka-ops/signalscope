import io
import json
import uuid
from pathlib import Path

import pytest

from signalscope.cli import build_parser, release_readiness
from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.acceptance_profile import AcceptanceProfile
from signalscope.domain.diagnostics.release_readiness import ReleaseReadinessService

pytestmark = pytest.mark.anyio


def test_arguments() -> None:
    organization_id = uuid.uuid4()
    args = build_parser().parse_args(
        [
            "release-readiness",
            "--profile",
            "acceptance.json",
            "--organization-id",
            str(organization_id),
            "--deployment-profile",
            "deployment.json",
            "--json",
        ]
    )

    assert args.profile == Path("acceptance.json")
    assert args.organization_id == organization_id
    assert args.deployment_profile == Path("deployment.json")
    assert args.json is True


async def test_json_output_and_failed_exit() -> None:
    profile = AcceptanceProfile(1, {"deployment": {"migration_current": True}})
    report = await ReleaseReadinessService(Settings()).collect(profile, session=None, blobs=None)
    out = io.StringIO()

    code = await release_readiness(
        Path("unused.json"), Settings(), out, json_output=True, report=report
    )
    payload = json.loads(out.getvalue())

    assert code == 1
    assert payload["acceptance"]["requirements_missed"] == ["deployment.migration_current"]


async def test_invalid_profile() -> None:
    err = io.StringIO()

    code = await release_readiness(Path("missing.json"), Settings(), err=err)

    assert code == 1
    assert "Error:" in err.getvalue()
