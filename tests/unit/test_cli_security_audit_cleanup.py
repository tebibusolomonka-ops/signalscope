import pytest

from signalscope.cli import build_parser, main


def test_arguments() -> None:
    parser = build_parser()
    default = parser.parse_args(["cleanup-security-audit"])
    assert (default.limit, default.apply) == (1000, False)
    applied = parser.parse_args(["cleanup-security-audit", "--limit", "5", "--apply"])
    assert (applied.limit, applied.apply) == (5, True)


def test_missing_database_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SIGNALSCOPE_DATABASE_URL", raising=False)

    assert main(["cleanup-security-audit"]) == 1
    assert "Database URL is not configured" in capsys.readouterr().err
