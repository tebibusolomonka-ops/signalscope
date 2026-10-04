import io
import uuid
from pathlib import Path

import pytest

from signalscope.cli import build_parser, restore_organization
from signalscope.core.settings import Settings

pytestmark = pytest.mark.anyio


def test_restore_arguments_default_to_dry_run() -> None:
    organization_id = uuid.uuid4()
    defaults = build_parser().parse_args(
        ["restore-organization", "tenant.zip", str(organization_id)]
    )

    assert defaults.path == Path("tenant.zip")
    assert defaults.organization_id == organization_id
    assert defaults.apply is False
    assert defaults.map == []
    assert defaults.json is False


def test_restore_arguments_with_apply_and_mappings() -> None:
    organization_id = uuid.uuid4()
    args = build_parser().parse_args(
        [
            "restore-organization",
            "tenant.zip",
            str(organization_id),
            "--apply",
            "--map",
            "a:b",
            "--map",
            "c:d",
            "--json",
        ]
    )

    assert args.apply is True
    assert args.map == ["a:b", "c:d"]
    assert args.json is True


async def test_restore_reports_missing_file(tmp_path: Path) -> None:
    out, err = io.StringIO(), io.StringIO()

    code = await restore_organization(tmp_path / "missing.zip", uuid.uuid4(), Settings(), out, err)

    assert code == 1
    assert "Cannot read" in err.getvalue()


async def test_restore_needs_a_database(tmp_path: Path) -> None:
    path = tmp_path / "tenant.zip"
    path.write_bytes(b"data")
    out, err = io.StringIO(), io.StringIO()

    code = await restore_organization(path, uuid.uuid4(), Settings(), out, err)

    assert code == 1
    assert "SIGNALSCOPE_DATABASE_URL" in err.getvalue()


async def test_restore_reports_bad_mapping(tmp_path: Path) -> None:
    path = tmp_path / "tenant.zip"
    path.write_bytes(b"data")
    out, err = io.StringIO(), io.StringIO()

    code = await restore_organization(
        path,
        uuid.uuid4(),
        Settings(database_url="postgresql+asyncpg://localhost/signalscope_test"),
        out,
        err,
        apply=True,
        mappings=["not-a-pair"],
    )

    assert code == 1
    assert "--map" in err.getvalue()
