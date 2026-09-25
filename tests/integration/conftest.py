import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from signalscope.api.app import create_app
from signalscope.api.lifespan import lifespan
from signalscope.core.settings import Settings
from signalscope.db.engine import create_database_engine
from signalscope.db.models import Base
from signalscope.db.session import create_session_factory

TEST_DATABASE_URL_VARIABLE = "SIGNALSCOPE_TEST_DATABASE_URL"
ALEMBIC_INI = Path(__file__).parents[2] / "alembic.ini"


@pytest.fixture(scope="session")
def test_database_settings() -> Settings:
    """Settings for the test database. Tests that use it skip when it is not set."""
    url = os.environ.get(TEST_DATABASE_URL_VARIABLE, "").strip()
    if not url:
        pytest.skip(f"{TEST_DATABASE_URL_VARIABLE} is not set")
    # These tests delete data, so only run them on a database meant for tests.
    database_name = make_url(url).database or ""
    if not database_name.endswith("_test"):
        pytest.fail(
            f"{TEST_DATABASE_URL_VARIABLE} must use a database whose name ends with _test",
            pytrace=False,
        )
    return Settings(database_url=url)


@pytest.fixture(scope="session")
def test_alembic_config(test_database_settings: Settings) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["settings"] = test_database_settings
    return config


@pytest.fixture(scope="session")
def migrated_database(test_alembic_config: Config, test_database_settings: Settings) -> Settings:
    command.upgrade(test_alembic_config, "head")
    return test_database_settings


@pytest.fixture
async def database_engine(migrated_database: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_database_engine(migrated_database)
    # Each test starts with empty tables, so tests do not depend on each other.
    async with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(database_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(database_engine)


@pytest.fixture
async def client(
    database_engine: AsyncEngine, migrated_database: Settings
) -> AsyncIterator[httpx.AsyncClient]:
    """An API client for the app running against the test database."""
    app = create_app(migrated_database)
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
