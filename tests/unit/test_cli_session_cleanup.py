import pytest

from signalscope.cli import build_parser, main
from signalscope.core.settings import Settings, SettingsError, load_settings


def test_retention_setting() -> None:
    assert Settings().auth_session_retention_days == 30
    found = load_settings({"SIGNALSCOPE_AUTH_SESSION_RETENTION_DAYS": "90"})
    assert found.auth_session_retention_days == 90


@pytest.mark.parametrize("days", ["0", "3651", "-1"])
def test_retention_bounds(days: str) -> None:
    with pytest.raises(SettingsError, match="auth_session_retention_days"):
        load_settings({"SIGNALSCOPE_AUTH_SESSION_RETENTION_DAYS": days})


def test_arguments() -> None:
    assert build_parser().parse_args(["cleanup-auth-sessions"]).limit == 1000
    assert build_parser().parse_args(["cleanup-auth-sessions", "--limit", "5"]).limit == 5


def test_bad_limit(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["cleanup-auth-sessions", "--limit", "0"])

    assert exit_info.value.code == 2
    assert "must be at least 1" in capsys.readouterr().err


def test_missing_database_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SIGNALSCOPE_DATABASE_URL", raising=False)

    assert main(["cleanup-auth-sessions"]) == 1
    assert capsys.readouterr().err == (
        "Error: Database URL is not configured. Set SIGNALSCOPE_DATABASE_URL.\n"
    )
