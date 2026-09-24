from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from signalscope.core.settings import SettingsError

ALEMBIC_INI = Path(__file__).parents[2] / "alembic.ini"


@pytest.fixture
def alembic_config(monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.delenv("SIGNALSCOPE_DATABASE_URL", raising=False)
    return Config(str(ALEMBIC_INI))


def test_migrations_have_at_most_one_head(alembic_config: Config) -> None:
    heads = ScriptDirectory.from_config(alembic_config).get_heads()

    assert len(heads) <= 1


def test_offline_migrations_do_not_need_a_database(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head", sql=True)


def test_online_migrations_need_database_url(alembic_config: Config) -> None:
    with pytest.raises(SettingsError, match="Database URL is not configured"):
        command.upgrade(alembic_config, "head")
