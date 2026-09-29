import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from signalscope.core.settings import Settings, SettingsError, load_settings
from signalscope.db.models import Base
from signalscope.domain.users.session import UserSession


def test_user_sessions_table() -> None:
    sql = str(CreateTable(UserSession.__table__).compile(dialect=postgresql.dialect()))

    assert "token_hash VARCHAR(64) NOT NULL" in sql
    assert "UNIQUE (token_hash)" in sql
    assert "CHECK (token_hash ~ '^[0-9a-f]{64}$')" in sql
    assert "expires_at TIMESTAMP WITH TIME ZONE NOT NULL" in sql
    assert "revoked_at TIMESTAMP WITH TIME ZONE," in sql
    assert "FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE" in sql
    # Only the hash is stored.
    assert " token " not in sql and "token VARCHAR" not in sql
    assert {index.name for index in UserSession.__table__.indexes} == {
        "ix_user_sessions_user_id",
        "ix_user_sessions_expires_at",
    }
    assert Base.metadata.tables["user_sessions"] is UserSession.__table__


def test_session_days_setting() -> None:
    assert Settings().auth_session_days == 7
    assert load_settings({"SIGNALSCOPE_AUTH_SESSION_DAYS": "30"}).auth_session_days == 30


@pytest.mark.parametrize("days", ["0", "366", "-1"])
def test_session_days_bounds(days: str) -> None:
    with pytest.raises(SettingsError, match="auth_session_days"):
        load_settings({"SIGNALSCOPE_AUTH_SESSION_DAYS": days})


def test_session_days_must_be_a_number() -> None:
    with pytest.raises(SettingsError, match="SIGNALSCOPE_AUTH_SESSION_DAYS"):
        load_settings({"SIGNALSCOPE_AUTH_SESSION_DAYS": "week"})
