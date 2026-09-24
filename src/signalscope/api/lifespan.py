import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from signalscope.core.logging import configure_logging
from signalscope.core.settings import Settings
from signalscope.db.engine import create_database_engine
from signalscope.db.session import create_session_factory

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run startup work before the app serves requests and shutdown work after.

    Logging is set up here and not in create_app, so building an app in tests
    does not change global logging.

    The database is optional for now. Without a database URL,
    app.state.session_factory is None.
    """
    settings: Settings = app.state.settings
    configure_logging(settings)

    engine: AsyncEngine | None = None
    app.state.session_factory = None
    if settings.database_url is None:
        logger.info("Database URL is not set, so database features are off")
    else:
        engine = create_database_engine(settings)
        app.state.session_factory = create_session_factory(engine)

    logger.info("%s started in %s", settings.app_name, settings.environment)
    try:
        yield
    finally:
        if engine is not None:
            await engine.dispose()
        logger.info("%s stopped", settings.app_name)
