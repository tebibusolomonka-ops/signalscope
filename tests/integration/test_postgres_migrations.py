from collections.abc import AsyncIterator, Callable

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from anyio import to_thread
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from signalscope.db.models import Base

pytestmark = pytest.mark.anyio


@pytest.fixture
async def migration_config(
    test_alembic_config: Config, database_engine: AsyncEngine
) -> AsyncIterator[Config]:
    """Config for tests that move the schema. It is put back to head afterwards."""
    yield test_alembic_config
    await run_alembic(command.upgrade, test_alembic_config, "head")


async def run_alembic(
    alembic_command: Callable[[Config, str], None], config: Config, revision: str
) -> None:
    # env.py calls asyncio.run, which cannot run inside the test's event loop.
    await to_thread.run_sync(alembic_command, config, revision)


async def table_names(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as connection:
        names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    return set(names)


async def current_revision(engine: AsyncEngine) -> str | None:
    async with engine.connect() as connection:
        return await connection.run_sync(
            lambda sync: MigrationContext.configure(sync).get_current_revision()
        )


async def test_upgrade_from_empty_database(
    migration_config: Config, database_engine: AsyncEngine
) -> None:
    await run_alembic(command.downgrade, migration_config, "base")
    await run_alembic(command.upgrade, migration_config, "head")

    assert await table_names(database_engine) == {
        "alembic_version",
        "sources",
        "documents",
        "ingestion_runs",
        "ingestion_jobs",
        "document_assets",
        "document_extractions",
        "document_processing_jobs",
        "document_chunks",
        "blob_cleanup_tasks",
        "document_revisions",
        "chunk_embeddings",
    }
    head = ScriptDirectory.from_config(migration_config).get_current_head()
    assert await current_revision(database_engine) == head


async def test_every_revision_downgrades_one_step_at_a_time(
    migration_config: Config, database_engine: AsyncEngine
) -> None:
    # walk_revisions starts at the head and goes back to the first revision.
    for revision in ScriptDirectory.from_config(migration_config).walk_revisions():
        assert await current_revision(database_engine) == revision.revision
        await run_alembic(command.downgrade, migration_config, "-1")

    assert await current_revision(database_engine) is None

    await run_alembic(command.upgrade, migration_config, "head")
    assert "ingestion_runs" in await table_names(database_engine)


async def test_downgrade_removes_all_tables(
    migration_config: Config, database_engine: AsyncEngine
) -> None:
    await run_alembic(command.downgrade, migration_config, "base")

    assert await table_names(database_engine) == {"alembic_version"}
    assert await current_revision(database_engine) is None


@pytest.mark.parametrize("table", ["documents", "ingestion_runs"])
async def test_table_references_sources(database_engine: AsyncEngine, table: str) -> None:
    async with database_engine.connect() as connection:
        foreign_keys = await connection.run_sync(lambda sync: inspect(sync).get_foreign_keys(table))

    [foreign_key] = foreign_keys
    assert foreign_key["constrained_columns"] == ["source_id"]
    assert foreign_key["referred_table"] == "sources"
    assert foreign_key["options"]["ondelete"] == "RESTRICT"


async def test_migrations_match_models(database_engine: AsyncEngine) -> None:
    async with database_engine.connect() as connection:
        differences = await connection.run_sync(
            lambda sync: compare_metadata(MigrationContext.configure(sync), Base.metadata)
        )

    assert differences == []
