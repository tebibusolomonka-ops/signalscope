import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from signalscope.core.logging import configure_logging
from signalscope.core.settings import Settings, load_settings
from signalscope.db.base import Base
from signalscope.db.engine import create_database_engine

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    # Offline mode only writes SQL, so it needs the dialect but not a database.
    context.configure(
        dialect_name="postgresql",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online(settings: Settings) -> None:
    engine = create_database_engine(settings)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


settings = load_settings()
configure_logging(settings)

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online(settings))
