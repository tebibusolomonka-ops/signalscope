import pytest

from signalscope.cli import build_parser, main
from signalscope.core.settings import Settings, SettingsError, load_settings


def test_retention_setting() -> None:
    assert Settings().organization_invitation_retention_days == 30
    found = load_settings({"SIGNALSCOPE_ORGANIZATION_INVITATION_RETENTION_DAYS": "90"})
    assert found.organization_invitation_retention_days == 90


@pytest.mark.parametrize("days", ["0", "366"])
def test_retention_bounds(days: str) -> None:
    with pytest.raises(SettingsError, match="organization_invitation_retention_days"):
        load_settings({"SIGNALSCOPE_ORGANIZATION_INVITATION_RETENTION_DAYS": days})


def test_arguments() -> None:
    parser = build_parser()
    assert parser.parse_args(["cleanup-organization-invitations"]).limit == 1000
    assert parser.parse_args(["cleanup-organization-invitations", "--limit", "3"]).limit == 3


def test_missing_database_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SIGNALSCOPE_DATABASE_URL", raising=False)

    assert main(["cleanup-organization-invitations"]) == 1
    assert "Database URL is not configured" in capsys.readouterr().err
