import io
import uuid
from pathlib import Path

import pytest

from signalscope import cli
from signalscope.cli import MIME_TYPES, build_parser, import_file, main
from signalscope.core.settings import Settings

# The .invalid domain never resolves, and these tests fail before connecting.
FAKE_DATABASE_URL = "postgresql+asyncpg://signalscope@db.invalid/signalscope"

pytestmark = pytest.mark.anyio


def settings(tmp_path: Path) -> Settings:
    return Settings(database_url=FAKE_DATABASE_URL, blob_dir=tmp_path / "blobs")


async def run(
    path: Path, settings: Settings, content_type: str | None = None
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = await import_file(uuid.uuid4(), path, settings, content_type, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_arguments() -> None:
    source_id = uuid.uuid4()

    args = build_parser().parse_args(
        ["import-file", str(source_id), "notes.txt", "--content-type", "text/plain"]
    )

    assert (args.command, args.source_id, args.path) == (
        "import-file",
        source_id,
        Path("notes.txt"),
    )
    assert args.content_type == "text/plain"
    assert build_parser().parse_args(["import-file", str(source_id), "a.pdf"]).content_type is None


def test_bad_source_id_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["import-file", "not-a-uuid", "notes.txt"])

    assert exit_info.value.code == 2
    assert "invalid UUID value: 'not-a-uuid'" in capsys.readouterr().err


def test_missing_database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SIGNALSCOPE_DATABASE_URL", raising=False)
    monkeypatch.setenv("SIGNALSCOPE_BLOB_DIR", str(tmp_path))

    assert main(["import-file", str(uuid.uuid4()), "notes.txt"]) == 1
    assert capsys.readouterr().err == (
        "Error: Database URL is not configured. Set SIGNALSCOPE_DATABASE_URL.\n"
    )


async def test_missing_blob_dir(tmp_path: Path) -> None:
    file = tmp_path / "notes.txt"
    file.write_bytes(b"hello")

    result = await run(file, Settings(database_url=FAKE_DATABASE_URL))

    assert result == (1, "", "Error: Blob directory is not configured. Set SIGNALSCOPE_BLOB_DIR.\n")


async def test_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.txt"

    code, out, err = await run(missing, settings(tmp_path))

    assert (code, out) == (1, "")
    assert err == f"Error: File was not found: {missing}\n"


async def test_folder_is_not_a_file(tmp_path: Path) -> None:
    code, _, err = await run(tmp_path, settings(tmp_path))

    assert code == 1
    assert err.startswith("Error: File was not found:")


async def test_unknown_content_type(tmp_path: Path) -> None:
    file = tmp_path / "data.xyz123"
    file.write_bytes(b"hello")

    result = await run(file, settings(tmp_path))

    assert result == (
        1,
        "",
        "Error: Could not tell the content type of data.xyz123. Use --content-type.\n",
    )


async def test_large_file_is_rejected_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "big.txt"
    file.write_bytes(b"x" * 11)
    monkeypatch.setattr(cli, "MAX_FILE_BYTES", 10)

    code, _, err = await run(file, settings(tmp_path))

    assert code == 1
    assert err.startswith("Error: File is larger than")


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("notes.txt", "text/plain"),
        ("data.json", "application/json"),
        ("page.html", "text/html"),
        ("page.xhtml", "application/xhtml+xml"),
        ("report.pdf", "application/pdf"),
        ("letter.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("REPORT.PDF", "application/pdf"),
        ("no-extension", None),
    ],
)
def test_content_type_guesses(filename: str, content_type: str | None) -> None:
    assert MIME_TYPES.guess_type(filename)[0] == content_type
