import io
import uuid
from pathlib import Path

import pytest

from signalscope.cli import (
    _write_atomically,
    _write_bytes_atomically,
    build_parser,
    export_investigation,
    export_organization,
)
from signalscope.core.exports import ExportFormat
from signalscope.core.settings import Settings

pytestmark = pytest.mark.anyio


def test_arguments() -> None:
    investigation_id = uuid.uuid4()
    args = build_parser().parse_args(
        [
            "export-investigation",
            str(investigation_id),
            "--format",
            "markdown",
            "--output",
            "report.md",
            "--overwrite",
        ]
    )

    assert (args.investigation_id, args.format, args.output, args.overwrite) == (
        investigation_id,
        ExportFormat.MARKDOWN,
        Path("report.md"),
        True,
    )
    defaults = build_parser().parse_args(["export-investigation", str(investigation_id)])
    assert (defaults.format, defaults.output, defaults.overwrite) == (
        ExportFormat.JSON,
        None,
        False,
    )


def test_bad_format(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["export-investigation", str(uuid.uuid4()), "--format", "pdf"])

    assert "argument --format" in capsys.readouterr().err


def test_organization_export_arguments() -> None:
    organization_id = uuid.uuid4()
    args = build_parser().parse_args(
        [
            "export-organization",
            str(organization_id),
            "--output",
            "tenant.zip",
            "--overwrite",
        ]
    )

    assert (args.organization_id, args.output, args.overwrite) == (
        organization_id,
        Path("tenant.zip"),
        True,
    )


async def test_existing_file_is_not_replaced(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text("keep me", encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()

    code = await export_investigation(uuid.uuid4(), Settings(), out, err, output=path)

    assert code == 1
    assert "already exists. Use --overwrite" in err.getvalue()
    assert path.read_text(encoding="utf-8") == "keep me"


async def test_needs_a_database() -> None:
    out, err = io.StringIO(), io.StringIO()

    assert await export_investigation(uuid.uuid4(), Settings(), out, err) == 1
    assert "SIGNALSCOPE_DATABASE_URL" in err.getvalue()


async def test_organization_export_needs_a_database(tmp_path: Path) -> None:
    out, err = io.StringIO(), io.StringIO()

    assert (
        await export_organization(uuid.uuid4(), tmp_path / "tenant.zip", Settings(), out, err) == 1
    )
    assert "SIGNALSCOPE_DATABASE_URL" in err.getvalue()


def test_atomic_write_replaces_whole_file(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text("old", encoding="utf-8")

    _write_atomically(path, "new text\n")

    assert path.read_text(encoding="utf-8") == "new text\n"
    # No temporary file is left behind.
    assert [item.name for item in tmp_path.iterdir()] == ["report.md"]


def test_atomic_write_leaves_nothing_on_failure(tmp_path: Path) -> None:
    missing_folder = tmp_path / "missing" / "report.md"

    with pytest.raises(OSError):
        _write_atomically(missing_folder, "text")

    assert list(tmp_path.iterdir()) == []


def test_atomic_binary_write_replaces_whole_file(tmp_path: Path) -> None:
    path = tmp_path / "tenant.zip"
    path.write_bytes(b"old")

    _write_bytes_atomically(path, b"new archive")

    assert path.read_bytes() == b"new archive"
    assert [item.name for item in tmp_path.iterdir()] == ["tenant.zip"]
