import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.core.settings import Settings, SettingsError, load_settings
from signalscope.db.models import Base
from signalscope.domain.users.throttle import AuthenticationThrottle


def test_authentication_throttle_table() -> None:
    sql = str(CreateTable(AuthenticationThrottle.__table__).compile(dialect=postgresql.dialect()))

    assert "identifier VARCHAR(64) NOT NULL" in sql
    assert "PRIMARY KEY (identifier)" in sql
    assert "CHECK (identifier ~ '^[0-9a-f]{64}$')" in sql
    assert "CHECK (failure_count >= 0)" in sql
    assert "window_started_at TIMESTAMP WITH TIME ZONE NOT NULL" in sql
    assert "blocked_until TIMESTAMP WITH TIME ZONE" in sql
    assert "updated_at TIMESTAMP WITH TIME ZONE" in sql
    assert {index.name for index in AuthenticationThrottle.__table__.indexes} == {
        "ix_authentication_throttles_blocked_until",
        "ix_authentication_throttles_updated_at",
    }
    assert Base.metadata.tables["authentication_throttles"] is AuthenticationThrottle.__table__


def test_login_throttle_setting_defaults_and_environment() -> None:
    defaults = Settings()
    assert (
        defaults.auth_login_window_seconds,
        defaults.auth_login_max_failures,
        defaults.auth_login_block_seconds,
    ) == (900, 10, 900)
    loaded = load_settings(
        {
            "SIGNALSCOPE_AUTH_LOGIN_WINDOW_SECONDS": "120",
            "SIGNALSCOPE_AUTH_LOGIN_MAX_FAILURES": "5",
            "SIGNALSCOPE_AUTH_LOGIN_BLOCK_SECONDS": "300",
        }
    )
    assert (
        loaded.auth_login_window_seconds,
        loaded.auth_login_max_failures,
        loaded.auth_login_block_seconds,
    ) == (120, 5, 300)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SIGNALSCOPE_AUTH_LOGIN_WINDOW_SECONDS", "0"),
        ("SIGNALSCOPE_AUTH_LOGIN_WINDOW_SECONDS", "86401"),
        ("SIGNALSCOPE_AUTH_LOGIN_MAX_FAILURES", "101"),
        ("SIGNALSCOPE_AUTH_LOGIN_BLOCK_SECONDS", "604801"),
    ],
)
def test_login_throttle_setting_bounds(name: str, value: str) -> None:
    with pytest.raises(SettingsError, match="auth_login"):
        load_settings({name: value})
