import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from signalscope.core.settings import Settings, SettingsError
from signalscope.db.engine import create_database_engine


@pytest.mark.anyio
async def test_creates_async_engine_for_database_url() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://signalscope:signalscope@localhost:5432/signalscope"
    )

    engine = create_database_engine(settings)

    assert isinstance(engine, AsyncEngine)
    assert engine.url.drivername == "postgresql+asyncpg"
    assert engine.url.database == "signalscope"
    await engine.dispose()


@pytest.mark.anyio
async def test_creating_engine_does_not_connect() -> None:
    # The .invalid domain never resolves, so any connection attempt would fail.
    settings = Settings(database_url="postgresql+asyncpg://signalscope@db.invalid/signalscope")

    engine = create_database_engine(settings)

    await engine.dispose()


def test_missing_database_url_is_rejected() -> None:
    with pytest.raises(SettingsError, match="Database URL is not configured"):
        create_database_engine(Settings())
