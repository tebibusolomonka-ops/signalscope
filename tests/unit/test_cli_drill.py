import io
import uuid

import pytest

from signalscope.cli import build_parser, run_disaster_recovery_drill
from signalscope.core.settings import Settings

pytestmark = pytest.mark.anyio


def test_arguments_default_to_verification() -> None:
    organization_id = uuid.uuid4()
    args = build_parser().parse_args(["run-disaster-recovery-drill", str(organization_id)])

    assert args.organization_id == organization_id
    assert args.mode == "verification-only"
    assert args.target_organization is None
    assert args.include_assets is True
    assert args.map == []


def test_restore_test_arguments() -> None:
    organization_id = uuid.uuid4()
    target = uuid.uuid4()
    args = build_parser().parse_args(
        [
            "run-disaster-recovery-drill",
            str(organization_id),
            "--mode",
            "restore-test",
            "--target-organization",
            str(target),
            "--no-include-assets",
            "--map",
            "a:b",
        ]
    )

    assert args.mode == "restore-test"
    assert args.target_organization == target
    assert args.include_assets is False
    assert args.map == ["a:b"]


async def test_needs_a_database() -> None:
    out, err = io.StringIO(), io.StringIO()

    code = await run_disaster_recovery_drill(uuid.uuid4(), Settings(), out, err)

    assert code == 1
    assert "SIGNALSCOPE_DATABASE_URL" in err.getvalue()
