import io
from pathlib import Path

import pytest

from signalscope.cli import build_parser, main, run_processing_worker
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these tests fail before connecting.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"


def test_arguments() -> None:
    args = build_parser().parse_args(["run-processing-worker", "--once"])

    assert (args.command, args.once) == ("run-processing-worker", True)


def test_missing_database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SIGNALSCOPE_DATABASE_URL", raising=False)
    monkeypatch.setenv("SIGNALSCOPE_BLOB_DIR", str(tmp_path))

    assert main(["run-processing-worker", "--once"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Error: Database URL is not configured. Set SIGNALSCOPE_DATABASE_URL.\n"


@pytest.mark.anyio
async def test_missing_blob_dir() -> None:
    out, err = io.StringIO(), io.StringIO()

    code = await run_processing_worker(Settings(database_url=FAKE_DATABASE_URL), out, err)

    assert (code, out.getvalue()) == (1, "")
    assert err.getvalue() == "Error: Blob directory is not configured. Set SIGNALSCOPE_BLOB_DIR.\n"
