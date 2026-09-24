import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from signalscope.core.logging import configure_logging
from signalscope.core.settings import Settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run startup work before the app serves requests and shutdown work after.

    Logging is set up here and not in create_app, so building an app in tests
    does not change global logging.
    """
    settings: Settings = app.state.settings
    configure_logging(settings)
    logger.info("%s started in %s", settings.app_name, settings.environment)
    yield
    logger.info("%s stopped", settings.app_name)
