import io
from pathlib import Path

import pytest

from signalscope.cli import build_parser, cleanup_blobs, main
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these tests fail before connecting.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_arguments() -> None:
    assert build_parser().parse_args(["cleanup-blobs"]).limit == 100
    assert build_parser().parse_args(["cleanup-blobs", "--limit", "5"]).limit == 5


def test_bad_limit(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["cleanup-blobs", "--limit", "0"])

    assert exit_info.value.code == 2
    assert "must be at least 1" in capsys.readouterr().err


def test_missing_database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SIGNALSCOPE_DATABASE_URL", raising=False)
    monkeypatch.setenv("SIGNALSCOPE_BLOB_DIR", str(tmp_path))

    assert main(["cleanup-blobs"]) == 1
    assert capsys.readouterr().err == (
        "Error: Database URL is not configured. Set SIGNALSCOPE_DATABASE_URL.\n"
    )


@pytest.mark.anyio
async def test_missing_blob_dir() -> None:
    out, err = io.StringIO(), io.StringIO()

    code = await cleanup_blobs(10, Settings(database_url=FAKE_DATABASE_URL), out, err)

    assert (code, out.getvalue()) == (1, "")
    assert err.getvalue() == "Error: Blob directory is not configured. Set SIGNALSCOPE_BLOB_DIR.\n"
